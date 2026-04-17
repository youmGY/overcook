#!/usr/bin/env python3
"""CLI entry point — argument parsing and game loop.

This module owns the top-level event loop and delegates all game logic
to :class:`overcook.game.Game`.  It can be invoked three ways::

    python main.py              # root shim
    python -m overcook          # package entry
    overcook (console script)   # after pip install
"""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

import pygame

from overcook.engine import screen, clock, FPS
from overcook.game import Game
from overcook.input import GameInput, hand_inputs_to_game_input, merge_inputs

# ── logging ───────────────────────────────────────────────────────────────
logging.basicConfig(
    filename="game.log",
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── key → slot mapping ───────────────────────────────────────────────────
_SLOT_KEYS: dict[int, int] = {
    pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
    pygame.K_4: 4, pygame.K_5: 5,
}

MAX_DT = 0.05  # cap delta-time to avoid physics spikes


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description="Overcook — 오버쿡 스타일 요리 게임")
    parser.add_argument("-test", action="store_true", help="Use test button labels")
    parser.add_argument("-active", action="store_true", help="Show camera feed")
    parser.add_argument("--gesture", action="store_true",
                        help="Enable gesture recognition input")
    parser.add_argument("--flip", action="store_true", default=True,
                        help="Mirror camera horizontally (default: True)")
    return parser.parse_args()


def _resolve_ui_mode(args: argparse.Namespace) -> str:
    """Determine UI mode from parsed CLI arguments."""
    if args.active or args.gesture:
        return "active"
    if args.test:
        return "test"
    return "normal"


def _process_gesture(game: Game) -> tuple[GameInput, Optional[object]]:
    """Run one gesture-recognition step and return (GameInput, raw_frame)."""
    if not game.use_gesture:
        return GameInput(), None
    hand_inputs, frame = game.gesture_step()
    if not hand_inputs:
        return GameInput(), frame
    gi = hand_inputs_to_game_input(hand_inputs, overlay_active=game.overlay.active)
    return gi, frame


def _handle_events(
    game: Game,
    held: dict[str, bool],
) -> tuple[dict[str, object], bool]:
    """Process all pending pygame events.

    Returns
    -------
    frame_actions : dict
        Accumulated per-frame input flags (confirm, chop, stir, move_to_slot,
        station_click, overlay_click).
    mouse_pressed : bool
        Whether the left mouse button is currently held.
    """
    actions: dict[str, object] = {}
    mouse_pressed = False

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            game.shutdown()
            pygame.quit()
            sys.exit()

        if event.type == pygame.KEYDOWN:
            _on_key_down(event, game, held, actions)

        elif event.type == pygame.KEYUP:
            _on_key_up(event, held)

        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            mouse_pressed = True
            click_pos = pygame.mouse.get_pos()
            if game.overlay.active:
                actions["overlay_click"] = click_pos
            else:
                actions["station_click"] = click_pos

        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            mouse_pressed = False

    return actions, mouse_pressed


def _on_key_down(
    event: pygame.event.Event,
    game: Game,
    held: dict[str, bool],
    actions: dict[str, object],
) -> None:
    """Handle a single KEYDOWN event."""
    key = event.key

    # Movement
    if key in (pygame.K_LEFT, pygame.K_a):
        held["left"] = True
    if key in (pygame.K_RIGHT, pygame.K_d):
        held["right"] = True

    # Slot selection
    if key in _SLOT_KEYS and game.state == "play":
        actions["move_to_slot"] = _SLOT_KEYS[key]

    # Confirm / start
    if key in (pygame.K_z, pygame.K_SPACE):
        if game.state == "play":
            actions["confirm"] = True
        elif game.state in ("title", "over"):
            game.start_game()

    # Actions
    if key == pygame.K_c and game.state == "play":
        actions["chop"] = True
    if key == pygame.K_v and game.state == "play":
        actions["stir"] = True

    # Recipe overlay toggle
    if key == pygame.K_r and game.state == "play":
        game.recipe_overlay.active = not game.recipe_overlay.active
        game.overlay.active = False

    # Enter → start game
    if key == pygame.K_RETURN and game.state in ("title", "over"):
        game.start_game()

    # Escape → close overlays / pause / quit
    if key == pygame.K_ESCAPE:
        if game.recipe_overlay.active:
            game.recipe_overlay.active = False
        elif game.overlay.active:
            game.overlay.active = False
        elif game.state == "play":
            game.state = "paused"
        elif game.state == "paused":
            game.state = "play"
        else:
            game.shutdown()
            pygame.quit()
            sys.exit()


def _on_key_up(event: pygame.event.Event, held: dict[str, bool]) -> None:
    """Handle a single KEYUP event."""
    if event.key in (pygame.K_LEFT, pygame.K_a):
        held["left"] = False
    if event.key in (pygame.K_RIGHT, pygame.K_d):
        held["right"] = False


def _build_keyboard_input(
    held: dict[str, bool],
    actions: dict[str, object],
) -> GameInput:
    """Build a GameInput from keyboard state and frame actions."""
    move_dir = 0
    if held["left"]:
        move_dir = -1
    elif held["right"]:
        move_dir = 1

    return GameInput(
        move_dir=move_dir,
        move_to_slot=actions.get("move_to_slot"),
        station_click=actions.get("station_click"),
        confirm=actions.get("confirm", False),
        chop=actions.get("chop", False),
        stir=actions.get("stir", False),
        overlay_click=actions.get("overlay_click"),
    )


def _draw_frame(game: Game, pipeline_frame: object | None) -> None:
    """Dispatch drawing to the correct Game screen method."""
    draw_methods = {
        "title": game.draw_title,
        "over": game.draw_over,
        "paused": game.draw_paused,
    }
    draw = draw_methods.get(game.state)
    if draw:
        draw()
    else:
        game.draw(pipeline_frame)
    pygame.display.flip()


# ── main entry point ──────────────────────────────────────────────────────

def main() -> None:
    """Run the Overcook game loop."""
    args = _parse_args()
    ui_mode = _resolve_ui_mode(args)

    game = Game(ui_mode=ui_mode, use_gesture=args.gesture, flip=args.flip)
    held: dict[str, bool] = {"left": False, "right": False}

    log.info("Game started (ui_mode=%s, gesture=%s)", ui_mode, args.gesture)

    try:
        while True:
            dt = min(clock.tick(FPS) / 1000.0, MAX_DT)

            gesture_gi, pipeline_frame = _process_gesture(game)
            actions, mpressed = _handle_events(game, held)
            keyboard_gi = _build_keyboard_input(held, actions)
            gi = merge_inputs(keyboard_gi, gesture_gi)

            mpos = pygame.mouse.get_pos()
            game.update(dt, gi, mpos, mpressed)
            _draw_frame(game, pipeline_frame)
    except KeyboardInterrupt:
        pass
    finally:
        game.shutdown()
        pygame.quit()
