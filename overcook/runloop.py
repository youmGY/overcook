#!/usr/bin/env python3
"""Runtime loops and CLI entrypoint for Overcook."""

import argparse
import pygame
import sys

from .engine import clock, FPS
from .game import Game
from .input import (
    GameInput,
    hand_inputs_to_game_input,
    merge_inputs,
)


def _collect_local_input(game, held, _gi_frame, station_click, overlay_click) -> tuple:
    """Collect gesture + keyboard input for the local player. Returns (GameInput, frame)."""
    pipeline_frame = None
    gesture_gi = GameInput()
    if game.use_gesture:
        hand_inputs, pipeline_frame = game.gesture_step()
        if hand_inputs:
            local_overlay = game._player_overlays.get(game.local_player_id, False)
            any_thumbs_up = any(
                h.gesture == "thumbs_up" for h in hand_inputs if not h.stale
            )
            gesture_gi = hand_inputs_to_game_input(
                hand_inputs,
                overlay_active=local_overlay,
                thumbs_cooldown=game._thumbs_up_held,
            )
            if game._move_blocked:
                gesture_gi.move_to_slot = None
                game._move_blocked = False
            if not game._station_shortcuts_enabled():
                gesture_gi.move_to_slot = None
            game._thumbs_up_held = any_thumbs_up
        else:
            game._thumbs_up_held = False

    move_dir = 0
    if held["left"]:
        move_dir = -1
    elif held["right"]:
        move_dir = 1

    keyboard_gi = GameInput(
        move_dir=move_dir,
        move_to_slot=_gi_frame.get("move_to_slot"),
        station_click=station_click,
        confirm=_gi_frame.get("confirm", False),
        chop=_gi_frame.get("chop", False),
        stir=_gi_frame.get("stir", False),
        put_down=_gi_frame.get("put_down", False),
        overlay_click=overlay_click,
        overlay_cancel=_gi_frame.get("overlay_cancel", False),
    )
    return merge_inputs(keyboard_gi, gesture_gi), pipeline_frame


def _main_single(ui_mode: str, args):
    """Single player game loop."""
    game = Game(
        ui_mode=ui_mode,
        use_gesture=args.gesture,
        flip=args.flip,
        fast_motion=args.fast_motion,
        clahe=args.clahe,
        clahe_clip=args.clahe_clip,
        clahe_grid=args.clahe_grid,
        device=args.device,
    )
    game._start_game_session()
    held = {"left": False, "right": False}
    _gi_frame: dict = {}
    mpressed = False
    _click_this_frame = False
    station_click = None
    overlay_click = None
    pipeline_frame = None

    _SLOT_KEYS = {
        pygame.K_1: 1,
        pygame.K_2: 2,
        pygame.K_3: 3,
        pygame.K_4: 4,
        pygame.K_5: 5,
    }

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        _gi_frame = {}
        station_click = None
        overlay_click = None
        pipeline_frame = None
        _click_this_frame = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.shutdown()
                pygame.quit()
                sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    held["right"] = True
                if event.key in _SLOT_KEYS and game.state == "play" and game._station_shortcuts_enabled():
                    _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                if event.key in (pygame.K_z, pygame.K_SPACE):
                    if game.state == "play":
                        _gi_frame["confirm"] = True
                    elif game.state in ("title", "over"):
                        game._start_game_session()
                if event.key == pygame.K_c and game.state == "play":
                    _gi_frame["chop"] = True
                if event.key == pygame.K_v and game.state == "play":
                    _gi_frame["stir"] = True
                if event.key == pygame.K_g and game.state == "play":
                    _gi_frame["put_down"] = True
                if event.key == pygame.K_r:
                    if game.state == "play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game._player_overlays[game.local_player_id] = False
                        game.audio.play("page_flip")
                if event.key == pygame.K_RETURN:
                    if game.state in ("title", "over"):
                        game._start_game_session()
                if event.key == pygame.K_ESCAPE:
                    if game.recipe_overlay.active:
                        game.recipe_overlay.active = False
                        game.audio.play("page_flip")
                    elif game._player_overlays.get(game.local_player_id, False):
                        _gi_frame["overlay_cancel"] = True
                    elif game.state == "play":
                        game.state = "paused"
                        game.audio.play("ui_pause")
                        game.audio.pause_bgm()
                    elif game.state == "paused":
                        game.state = "play"
                        game.audio.play("ui_resume")
                        game.audio.unpause_bgm()
                    else:
                        game.shutdown()
                        pygame.quit()
                        sys.exit()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    held["left"] = False
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                _click_this_frame = True
                click_pos = pygame.mouse.get_pos()
                if game.settings_overlay.handle_mousedown(click_pos):
                    pass
                elif game._player_overlays.get(game.local_player_id, False):
                    overlay_click = click_pos
                elif game._station_shortcuts_enabled():
                    station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False
                game.settings_overlay.handle_mouseup(event.pos)
            if event.type == pygame.MOUSEMOTION:
                game.settings_overlay.handle_mousemove(event.pos)

        mpos = pygame.mouse.get_pos()
        gi, pipeline_frame = _collect_local_input(game, held, _gi_frame, station_click, overlay_click)
        game.update(dt, gi, mpos, _click_this_frame or mpressed)

        if game.state == "title":
            game.shutdown()
            return
        elif game.state == "over":
            game.draw_over()
        elif game.state == "paused":
            game.draw_paused()
        else:
            game.draw(pipeline_frame)

        pygame.display.flip()


def _main_multiplayer(ui_mode: str, args):
    """Multiplayer game loop with lobby."""
    from .network import GameServer, GameClient, RoomScanner, get_local_ip
    from .ui.lobby_ui import LobbyUI
    from .constants import NET_PORT, NET_TICK_RATE

    lobby_ui = LobbyUI()
    lobby_state = "lobby_menu"

    server = None
    client = None
    scanner = None
    game = None

    held = {"left": False, "right": False}
    mpressed = False
    click_pos = None
    client_paused = False

    _SLOT_KEYS = {pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3, pygame.K_4: 4, pygame.K_5: 5}

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        click_pos = None
        station_click = None
        overlay_click = None
        _gi_frame = {}
        _click_this_frame = False

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                if server:
                    server.stop()
                if client:
                    client.close()
                if scanner:
                    scanner.stop()
                if game:
                    game.shutdown()
                pygame.quit()
                return
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    held["right"] = True
                if event.key == pygame.K_ESCAPE and lobby_state.startswith("lobby"):
                    if server:
                        server.stop()
                    if client:
                        client.close()
                    if scanner:
                        scanner.stop()
                    pygame.quit()
                    return
                if lobby_state.startswith("playing") and game:
                    if game.state == "play":
                        if event.key == pygame.K_ESCAPE:
                            if game._player_overlays.get(getattr(game, "local_player_id", 0), False):
                                _gi_frame["overlay_cancel"] = True
                            elif lobby_state == "playing_host":
                                game.state = "paused"
                                game.audio.play("ui_pause")
                                game.audio.pause_bgm()
                        if event.key in _SLOT_KEYS and game._station_shortcuts_enabled():
                            _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                        if event.key in (pygame.K_z, pygame.K_SPACE):
                            _gi_frame["confirm"] = True
                        if event.key == pygame.K_c:
                            _gi_frame["chop"] = True
                        if event.key == pygame.K_v:
                            _gi_frame["stir"] = True
                    elif game.state == "paused" and event.key == pygame.K_ESCAPE and lobby_state == "playing_host":
                        game.state = "play"
                        game.audio.play("ui_resume")
                        game.audio.unpause_bgm()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a):
                    held["left"] = False
                if event.key in (pygame.K_RIGHT, pygame.K_d):
                    held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                _click_this_frame = True
                click_pos = pygame.mouse.get_pos()
                if game and game.settings_overlay.handle_mousedown(click_pos):
                    pass
                elif not lobby_state.startswith("playing") and lobby_ui.handle_mousedown(click_pos):
                    pass
                elif game and game._player_overlays.get(getattr(game, "local_player_id", 0), False):
                    overlay_click = click_pos
                elif lobby_state.startswith("playing") and game and game._station_shortcuts_enabled():
                    station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False
                if game:
                    game.settings_overlay.handle_mouseup(event.pos)
                if not lobby_state.startswith("playing"):
                    lobby_ui.handle_mouseup(event.pos)
            if event.type == pygame.MOUSEMOTION:
                if game:
                    game.settings_overlay.handle_mousemove(event.pos)
                if not lobby_state.startswith("playing"):
                    lobby_ui.handle_mousemove(event.pos)

        mpos = pygame.mouse.get_pos()
        _btn_pressed = _click_this_frame or mpressed

        if lobby_state == "lobby_menu":
            action = lobby_ui.update_menu(mpos, _btn_pressed)
            if action == "create":
                host_ip = get_local_ip()
                server = GameServer(host_ip, NET_PORT, room_name=f"{args.name}'s Room")
                server.start()
                lobby_state = "lobby_create"
                lobby_ui.players = [{"id": 0, "name": args.name, "ready": False}]
                lobby_ui.status_text = f"Listening on {host_ip}:{NET_PORT}"
            elif action == "join":
                scanner = RoomScanner()
                scanner.start()
                lobby_state = "lobby_join"
                lobby_ui.rooms = []
                lobby_ui.selected_room = -1
            elif action == "single":
                _main_single(ui_mode, args)
                mpressed = False
            lobby_ui.draw_menu()

        elif lobby_state == "lobby_create":
            action = lobby_ui.update_create(mpos, _btn_pressed)
            if action == "ready":
                server.set_host_ready(not server.host_ready)
            elif action == "start":
                info = server.get_lobby_info()
                if info["all_ready"] and info["count"] > 0:
                    player_names = {p["id"]: p["name"] for p in info["players"]}
                    game = Game(
                        ui_mode=ui_mode,
                        use_gesture=args.gesture,
                        flip=args.flip,
                        fast_motion=args.fast_motion,
                        clahe=args.clahe,
                        clahe_clip=args.clahe_clip,
                        clahe_grid=args.clahe_grid,
                        device=args.device,
                        multiplayer=True,
                        is_server=True,
                        local_player_id=0,
                        player_name=args.name,
                        audio=lobby_ui.audio,
                    )
                    game.set_mp_player_names(player_names)
                    game.reset()
                    game.state = "play"
                    game._spawn_order()
                    game._spawn_order()
                    game.audio.play("start_whistle")
                    game.audio.play_bgm("play_loop")
                    server.start_game()
                    lobby_state = "playing_host"
                    mpressed = False
                    continue
                else:
                    lobby_ui.status_text = "Not all players ready!"
            elif action == "back":
                server.stop()
                server = None
                lobby_state = "lobby_menu"
                continue

            info = server.get_lobby_info()
            lobby_ui.players = info["players"]
            lobby_ui.draw_create(f"{server.host}:{server.port}")

        elif lobby_state == "lobby_join":
            action = lobby_ui.update_join(mpos, _btn_pressed, click_pos=click_pos)
            if action == "connect":
                if 0 <= lobby_ui.selected_room < len(lobby_ui.rooms):
                    room = lobby_ui.rooms[lobby_ui.selected_room]
                    client = GameClient(room["host"], room["port"], args.name)
                    if client.connect():
                        lobby_state = "lobby_wait"
                        lobby_ui.status_text = f"Connected as Player {client.player_id + 1}"
                    else:
                        lobby_ui.status_text = "Connection failed!"
                        client = None
            elif action == "back":
                scanner.stop()
                scanner = None
                lobby_state = "lobby_menu"
                continue

            lobby_ui.rooms = scanner.get_rooms()
            lobby_ui.draw_join()

        elif lobby_state == "lobby_wait":
            action = lobby_ui.update_wait(mpos, _btn_pressed)
            if action == "ready":
                client.send_ready(True)
            elif action == "back":
                client.close()
                client = None
                lobby_state = "lobby_menu"
                continue

            try:
                msg = client.lobby_queue.get_nowait()
                lobby_ui.players = msg.get("players", [])
            except Exception:
                pass

            try:
                event_msg = client.event_queue.get_nowait()
                if event_msg.get("type") == "game_start":
                    player_names = {p["id"]: p["name"] for p in lobby_ui.players}
                    game = Game(
                        ui_mode=ui_mode,
                        use_gesture=args.gesture,
                        flip=args.flip,
                        fast_motion=args.fast_motion,
                        clahe=args.clahe,
                        clahe_clip=args.clahe_clip,
                        clahe_grid=args.clahe_grid,
                        device=args.device,
                        multiplayer=True,
                        is_server=False,
                        local_player_id=client.player_id,
                        player_name=args.name,
                        audio=lobby_ui.audio,
                    )
                    game.set_mp_player_names(player_names)
                    game.reset()
                    game.state = "play"
                    game.audio.play("start_whistle")
                    game.audio.play_bgm("play_loop")
                    lobby_state = "playing_client"
                    mpressed = False
            except Exception:
                pass

            lobby_ui.draw_wait()

        elif lobby_state == "playing_host":
            mpos = pygame.mouse.get_pos()

            if game.state != "play":
                game.update(dt, GameInput(), mpos, _btn_pressed)
                if game.state == "over":
                    server.broadcast_game_over(game.score)
                    server.stop()
                    game.draw_over()
                elif game.state == "title":
                    server.stop()
                    game.shutdown()
                    game = None
                    server = None
                    lobby_state = "lobby_menu"
                    lobby_ui.audio.play_bgm("intro_bgm")
                    mpressed = False
                    pygame.display.flip()
                    continue
                elif game.state == "paused":
                    server.broadcast_state(game.serialize_state())
                    game.draw_paused()
                pygame.display.flip()
                continue

            alive_pids = set([0] + server.get_alive_player_ids())
            for pid in list(game.players.keys()):
                if pid not in alive_pids:
                    del game.players[pid]
                    game._lock_modes.pop(pid, None)
                    game._player_overlays.pop(pid, None)
                    game._player_highlights.pop(pid, None)
                    game._motion_gates_per_player.pop(pid, None)

            host_gi, pipeline_frame = _collect_local_input(game, held, _gi_frame, station_click, overlay_click)

            btn_triggered = game.update_ui_buttons(mpos, _btn_pressed)
            if btn_triggered.get("confirm"):
                host_gi.confirm = True
            if btn_triggered.get("chop"):
                host_gi.chop = True
            if btn_triggered.get("stir"):
                host_gi.stir = True
            if btn_triggered.get("pause"):
                game.state = "paused"
                game.audio.play("ui_pause")
                game.audio.pause_bgm()

            net_inputs = server.collect_inputs()
            net_inputs[0] = host_gi.to_dict()

            server_tick_interval = 1.0 / NET_TICK_RATE
            game._server_tick_accum += dt

            ticked = False
            while game._server_tick_accum >= server_tick_interval:
                game.server_tick(server_tick_interval, net_inputs)
                game._server_tick_accum -= server_tick_interval
                ticked = True
                for pid in list(net_inputs.keys()):
                    inp = net_inputs[pid]
                    if isinstance(inp, dict):
                        net_inputs[pid] = {"move_dir": inp.get("move_dir", 0)}

            if ticked:
                server.broadcast_state(game.serialize_state())

            if game.state == "over":
                server.broadcast_game_over(game.score)
                server.stop()
                game.draw_over()
                pygame.display.flip()
                game.shutdown()
                return
            game.draw(pipeline_frame)
            pygame.display.flip()

        elif lobby_state == "playing_client":
            mpos = pygame.mouse.get_pos()

            if not client or not client.connected:
                if client:
                    client.close()
                if game:
                    game.shutdown()
                game = None
                client = None
                client_paused = False
                lobby_state = "lobby_menu"
                lobby_ui.status_text = "Disconnected from host"
                lobby_ui.audio.play_bgm("intro_bgm")
                mpressed = False
                pygame.display.flip()
                continue

            if game.state == "over":
                game.draw_over()
                pygame.display.flip()
                client.close()
                game.shutdown()
                return

            if client_paused:
                try:
                    state = client.state_queue.get_nowait()
                    saved_state = game.state
                    game.apply_state(state)
                    if game.state != "over":
                        game.state = saved_state
                except Exception:
                    pass
                try:
                    event_msg = client.event_queue.get_nowait()
                    if event_msg.get("type") == "game_over":
                        game.state = "over"
                        game.score = event_msg.get("score", game.score)
                        client_paused = False
                except Exception:
                    pass
                if game.state == "over":
                    game.draw_over()
                    pygame.display.flip()
                    client.close()
                    game.shutdown()
                    return
                game.update(dt, GameInput(), mpos, _btn_pressed)
                if game.state == "play":
                    client_paused = False
                    game.audio.play("ui_resume")
                    game.audio.unpause_bgm()
                elif game.state == "title":
                    client.close()
                    game.shutdown()
                    game = None
                    client = None
                    client_paused = False
                    lobby_state = "lobby_menu"
                    lobby_ui.audio.play_bgm("intro_bgm")
                    mpressed = False
                    pygame.display.flip()
                    continue
                else:
                    game.state = "paused"
                game.draw_paused()
                pygame.display.flip()
                continue

            local_gi, pipeline_frame = _collect_local_input(game, held, _gi_frame, station_click, overlay_click)

            btn_triggered = game.update_ui_buttons(mpos, _btn_pressed)
            if btn_triggered.get("confirm"):
                local_gi.confirm = True
            if btn_triggered.get("chop"):
                local_gi.chop = True
            if btn_triggered.get("stir"):
                local_gi.stir = True
            if btn_triggered.get("pause") and game.state == "play":
                client_paused = True
                game.state = "paused"
                game.audio.play("ui_pause")
                game.audio.pause_bgm()

            if not client_paused:
                client.send_input(local_gi.to_dict())

            try:
                state = client.state_queue.get_nowait()
                game.apply_state(state)
            except Exception:
                pass

            try:
                event_msg = client.event_queue.get_nowait()
                if event_msg.get("type") == "game_over":
                    game.state = "over"
                    game.score = event_msg.get("score", game.score)
            except Exception:
                pass

            if game.state == "paused":
                game.draw_paused()
            else:
                game.draw(pipeline_frame)
            pygame.display.flip()

        if not lobby_state.startswith("playing"):
            pygame.display.flip()


def main():
    parser = argparse.ArgumentParser(description="Overcook-style pygame game")
    parser.add_argument("-test", action="store_true", help="Use test button labels")
    parser.add_argument("-active", action="store_true", help="Show camera feed instead of action buttons")
    parser.add_argument(
        "--gesture",
        action="store_true",
        help="Enable gesture recognition input (camera + hand tracking)",
    )
    parser.add_argument("--flip", dest="flip", action="store_true", default=True, help="Mirror camera horizontally (default: on)")
    parser.add_argument("--no-flip", dest="flip", action="store_false", help="Disable camera mirroring")
    parser.add_argument("--fast-motion", action="store_true", help="Fast-motion preset for rapid chop/stir capture")
    parser.add_argument("--clahe", dest="clahe", action="store_true", default=True, help="Enable CLAHE brightness normalization (default: on)")
    parser.add_argument("--no-clahe", dest="clahe", action="store_false", help="Disable CLAHE brightness normalization")
    parser.add_argument("--clahe-clip", type=float, default=2.0, help="CLAHE clip limit (default: 2.0)")
    parser.add_argument("--clahe-grid", type=int, default=8, help="CLAHE tile grid size (default: 8)")
    parser.add_argument("--device", type=int, default=0, help="Camera device index (default: 0)")
    parser.add_argument(
        "--multiplayer",
        action="store_true",
        default=True,
        dest="multiplayer",
        help="Enable multiplayer mode (LAN lobby) [default: True]",
    )
    parser.add_argument("--single", action="store_true", help="Play in single player mode instead of multiplayer")
    parser.add_argument("--name", type=str, default="Player", help="Player name for multiplayer")
    args = parser.parse_args()

    ui_mode = "normal"
    if args.test:
        ui_mode = "test"
    if args.active or args.gesture:
        ui_mode = "active"

    if args.single:
        _main_single(ui_mode, args)
    else:
        _main_multiplayer(ui_mode, args)
