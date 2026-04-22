"""
Multiplayer networking layer for the Overcook cooking game.

Server-authoritative model:
  - GameServer: runs game logic, broadcasts state at NET_TICK_RATE
  - GameClient: sends local input, receives state snapshots
  - RoomAnnouncer / RoomScanner: UDP LAN room discovery
"""

import json
import queue
import select
import socket
import threading
import time
import logging
from typing import Callable, Dict, List, Optional

from .constants import NET_PORT, NET_DISCOVERY_PORT, NET_MAX_PLAYERS

log = logging.getLogger(__name__)


# ── helpers ───────────────────────────────────────────────────────────

def _send_json(sock: socket.socket, payload: dict):
    data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
    sock.sendall(data)


def _recv_json(reader) -> Optional[dict]:
    line = reader.readline()
    if not line:
        return None
    return json.loads(line.decode("utf-8").strip())


def get_local_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


# ── room discovery ────────────────────────────────────────────────────

class RoomAnnouncer:
    def __init__(self, room_name: str, host: str, port: int,
                 discovery_port: int = NET_DISCOVERY_PORT,
                 max_players: int = NET_MAX_PLAYERS):
        self.room_name = room_name
        self.host = host
        self.port = port
        self.discovery_port = discovery_port
        self.max_players = max_players
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            payload = json.dumps({
                "type": "room_announce",
                "name": self.room_name,
                "host": self.host,
                "port": self.port,
                "max_players": self.max_players,
            }, ensure_ascii=False).encode("utf-8")
            while not self._stop.is_set():
                try:
                    sock.sendto(payload, ("255.255.255.255", self.discovery_port))
                except OSError:
                    pass
                time.sleep(1.0)
        finally:
            sock.close()

    def stop(self):
        self._stop.set()


class RoomScanner:
    def __init__(self, discovery_port: int = NET_DISCOVERY_PORT):
        self.discovery_port = discovery_port
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._rooms: Dict[str, dict] = {}

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    data, _ = sock.recvfrom(4096)
                except socket.timeout:
                    self._evict()
                    continue
                except Exception:
                    continue
                try:
                    msg = json.loads(data.decode("utf-8"))
                except Exception:
                    continue
                if msg.get("type") != "room_announce":
                    continue
                host = msg.get("host")
                port = msg.get("port")
                if not host or not port:
                    continue
                key = f"{host}:{port}"
                with self._lock:
                    self._rooms[key] = {
                        "name": msg.get("name", "Room"),
                        "host": host,
                        "port": int(port),
                        "max_players": int(msg.get("max_players", NET_MAX_PLAYERS)),
                        "_seen": time.time(),
                    }
        finally:
            sock.close()

    def _evict(self):
        now = time.time()
        with self._lock:
            stale = [k for k, v in self._rooms.items() if now - v["_seen"] > 3.5]
            for k in stale:
                self._rooms.pop(k, None)

    def get_rooms(self) -> List[dict]:
        self._evict()
        with self._lock:
            return [
                {"name": r["name"], "host": r["host"], "port": r["port"],
                 "max_players": r["max_players"]}
                for r in sorted(self._rooms.values(), key=lambda r: r["name"])
            ]

    def stop(self):
        self._stop.set()


# ── client connection wrapper (used by server) ────────────────────────

class _ClientSlot:
    def __init__(self, conn: socket.socket, reader, player_id: int, name: str):
        self.conn = conn
        self.reader = reader
        self.player_id = player_id
        self.name = name
        self.ready = False
        self.alive = True
        self.input_queue: queue.Queue = queue.Queue(maxsize=8)
        # Non-blocking outbound queue — sender thread drains this
        self.send_queue: queue.Queue = queue.Queue(maxsize=32)
        self._send_thread = threading.Thread(target=self._send_loop, daemon=True)
        self._send_thread.start()

    def _send_loop(self):
        while self.alive:
            try:
                payload = self.send_queue.get(timeout=0.5)
            except queue.Empty:
                continue
            try:
                _send_json(self.conn, payload)
            except OSError as exc:
                log.warning("Client %s send failed: %s", self.player_id, exc)
                self.alive = False
                break

    def enqueue(self, payload: dict):
        """Put payload into send queue, dropping oldest if full."""
        try:
            self.send_queue.put_nowait(payload)
        except queue.Full:
            try:
                self.send_queue.get_nowait()  # drop oldest
            except queue.Empty:
                pass
            try:
                self.send_queue.put_nowait(payload)
            except queue.Full:
                pass


# ── game server ───────────────────────────────────────────────────────

class GameServer:
    """TCP server that manages lobby + game-state broadcast."""

    def __init__(self, host: str, port: int = NET_PORT,
                 max_players: int = NET_MAX_PLAYERS,
                 room_name: str = "Cooking Room"):
        self.host = host
        self.port = port
        self.max_players = max_players
        self.room_name = room_name

        self._server_sock: Optional[socket.socket] = None
        self._clients: List[_ClientSlot] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()

        self._announcer: Optional[RoomAnnouncer] = None
        self._accept_thread: Optional[threading.Thread] = None

        # Lobby state
        self.host_ready = False
        self.game_started = False

        # Callbacks (set by game)
        self.on_lobby_update: Optional[Callable] = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self):
        self._server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_sock.bind((self.host, self.port))
        self._server_sock.listen(self.max_players)
        self._server_sock.settimeout(1.0)

        self._announcer = RoomAnnouncer(self.room_name, self.host, self.port)
        self._announcer.start()

        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def stop(self):
        self._stop.set()
        if self._announcer:
            self._announcer.stop()
        with self._lock:
            for c in self._clients:
                try:
                    c.conn.close()
                except OSError:
                    pass
            self._clients.clear()
        if self._server_sock:
            try:
                self._server_sock.close()
            except OSError:
                pass

    # ── accept loop ───────────────────────────────────────────────────

    def _accept_loop(self):
        while not self._stop.is_set():
            if self._server_sock is None:
                break
            try:
                readable, _, _ = select.select([self._server_sock], [], [], 0.5)
            except Exception:
                break
            if not readable:
                continue
            try:
                conn, addr = self._server_sock.accept()
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except socket.timeout:
                continue
            except Exception:
                break

            reader = conn.makefile("rb")
            try:
                msg = _recv_json(reader)
            except Exception:
                conn.close()
                continue

            if not msg or msg.get("type") != "join":
                try:
                    _send_json(conn, {"type": "join_ack", "ok": False, "reason": "invalid"})
                except OSError:
                    pass
                conn.close()
                continue

            with self._lock:
                if len(self._clients) >= self.max_players - 1:  # -1 for host
                    _send_json(conn, {"type": "join_ack", "ok": False, "reason": "full"})
                    conn.close()
                    continue
                if self.game_started:
                    _send_json(conn, {"type": "join_ack", "ok": False, "reason": "in_progress"})
                    conn.close()
                    continue

                pid = len(self._clients) + 1  # host is 0
                name = msg.get("name", f"Player {pid + 1}")
                slot = _ClientSlot(conn, reader, pid, name)
                self._clients.append(slot)

                _send_json(conn, {
                    "type": "join_ack", "ok": True,
                    "player_id": pid, "name": name,
                })

            t = threading.Thread(target=self._recv_loop, args=(slot,), daemon=True)
            t.start()
            self._notify_lobby()

    # ── per-client receive loop ───────────────────────────────────────

    def _recv_loop(self, slot: _ClientSlot):
        while not self._stop.is_set() and slot.alive:
            try:
                readable, _, _ = select.select([slot.conn], [], [], 0.5)
            except Exception:
                break
            if not readable:
                continue
            try:
                msg = _recv_json(slot.reader)
            except Exception:
                break
            if msg is None:
                break

            mtype = msg.get("type")
            if mtype == "ready":
                with self._lock:
                    slot.ready = bool(msg.get("ready", True))
                self._notify_lobby()
            elif mtype == "player_input":
                try:
                    slot.input_queue.put_nowait(msg.get("input", {}))
                except queue.Full:
                    # Keep controls responsive: drop oldest queued input and keep latest.
                    try:
                        slot.input_queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        slot.input_queue.put_nowait(msg.get("input", {}))
                    except queue.Full:
                        pass

        with self._lock:
            slot.alive = False
        self._notify_lobby()

    # ── lobby helpers ─────────────────────────────────────────────────

    def get_lobby_info(self) -> dict:
        with self._lock:
            players = [{"id": 0, "name": "Host", "ready": self.host_ready}]
            for c in self._clients:
                if c.alive:
                    players.append({"id": c.player_id, "name": c.name, "ready": c.ready})
            return {
                "players": players,
                "all_ready": all(p["ready"] for p in players),
                "count": len(players),
            }

    def _notify_lobby(self):
        info = self.get_lobby_info()
        payload = {"type": "lobby_update", **info}
        self._broadcast(payload)
        if self.on_lobby_update:
            try:
                self.on_lobby_update(info)
            except OSError:
                pass

    def set_host_ready(self, ready: bool = True):
        self.host_ready = ready
        self._notify_lobby()

    def start_game(self):
        self.game_started = True
        if self._announcer:
            self._announcer.stop()
        self._broadcast({"type": "game_start"})

    # ── game-play helpers ─────────────────────────────────────────────

    def collect_inputs(self) -> Dict[int, dict]:
        """Drain input queues → {player_id: input_dict}. Non-blocking.

        One-shot boolean flags (confirm, chop, stir, action, put_down,
        overlay_confirm, overlay_cancel) are OR-merged across all queued
        frames so they are never silently dropped.
        """
        _OR_KEYS = ("confirm", "chop", "stir", "action", "put_down",
                    "overlay_confirm", "overlay_cancel")
        inputs = {}
        with self._lock:
            for c in self._clients:
                if not c.alive:
                    continue
                merged = None
                while True:
                    try:
                        frame = c.input_queue.get_nowait()
                    except queue.Empty:
                        break
                    if merged is None:
                        merged = dict(frame)
                    else:
                        for k in _OR_KEYS:
                            if frame.get(k):
                                merged[k] = True
                        for k in frame:
                            if k not in _OR_KEYS:
                                merged[k] = frame[k]
                if merged is not None:
                    inputs[c.player_id] = merged
        return inputs

    def broadcast_state(self, state: dict):
        self._broadcast({"type": "game_state", "state": state})

    def broadcast_game_over(self, score: int):
        self._broadcast({"type": "game_over", "score": score})

    def get_alive_player_ids(self) -> List[int]:
        with self._lock:
            return [c.player_id for c in self._clients if c.alive]

    # ── internal ──────────────────────────────────────────────────────

    def _broadcast(self, payload: dict):
        with self._lock:
            for c in self._clients:
                if c.alive:
                    c.enqueue(payload)


# ── game client ───────────────────────────────────────────────────────

class GameClient:
    """Connects to a GameServer, sends input, receives state."""

    def __init__(self, server_ip: str, port: int = NET_PORT, player_name: str = "Player"):
        self.server_ip = server_ip
        self.port = port
        self.player_name = player_name

        self._sock: Optional[socket.socket] = None
        self._reader = None
        self._stop = threading.Event()
        self._recv_thread: Optional[threading.Thread] = None

        self.player_id: Optional[int] = None
        self.connected = False

        # Incoming message queues (consumed by game loop)
        self.lobby_queue: queue.Queue = queue.Queue(maxsize=16)
        self.state_queue: queue.Queue = queue.Queue(maxsize=4)
        self.event_queue: queue.Queue = queue.Queue(maxsize=16)

    def connect(self) -> bool:
        try:
            self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._sock.settimeout(5.0)
            self._sock.connect((self.server_ip, self.port))
            self._sock.settimeout(None)
            self._reader = self._sock.makefile("rb")

            _send_json(self._sock, {"type": "join", "name": self.player_name})
            ack = _recv_json(self._reader)
            if not ack or not ack.get("ok"):
                self.close()
                return False

            self.player_id = ack.get("player_id")
            self.connected = True

            self._recv_thread = threading.Thread(target=self._recv_loop, daemon=True)
            self._recv_thread.start()
            return True
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            log.warning("GameClient.connect failed: %s", exc)
            self.close()
            return False

    def _recv_loop(self):
        while not self._stop.is_set() and self.connected:
            try:
                readable, _, _ = select.select([self._sock], [], [], 0.5)
            except Exception:
                break
            if not readable:
                continue
            try:
                msg = _recv_json(self._reader)
            except Exception:
                break
            if msg is None:
                break

            mtype = msg.get("type")
            if mtype == "lobby_update":
                try:
                    self.lobby_queue.put_nowait(msg)
                except queue.Full:
                    try:
                        self.lobby_queue.get_nowait()
                    except queue.Empty:
                        pass
                    self.lobby_queue.put_nowait(msg)
            elif mtype == "game_state":
                # Keep only latest state
                while not self.state_queue.empty():
                    try:
                        self.state_queue.get_nowait()
                    except queue.Empty:
                        break
                try:
                    self.state_queue.put_nowait(msg.get("state", {}))
                except queue.Full:
                    pass
            elif mtype in ("game_start", "game_over"):
                try:
                    self.event_queue.put_nowait(msg)
                except queue.Full:
                    pass

        self.connected = False

    def send_ready(self, ready: bool = True):
        if self._sock:
            try:
                _send_json(self._sock, {"type": "ready", "ready": ready})
            except Exception:
                self.connected = False

    def send_input(self, input_dict: dict):
        if self._sock:
            try:
                _send_json(self._sock, {"type": "player_input", "input": input_dict})
            except Exception:
                self.connected = False

    def close(self):
        self._stop.set()
        self.connected = False
        if self._reader:
            try:
                self._reader.close()
            except OSError:
                pass
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._reader = None
