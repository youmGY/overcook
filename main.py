#!/usr/bin/env python3
"""Overcook — 오버쿡 스타일 요리 게임.

실행: DISPLAY=:0 python game.py --gesture
설치: pip install pygame
"""
import argparse
import logging
import sys

import pygame

from overcook.engine import screen, clock, FPS
from overcook.game import Game
from overcook.input import GameInput, hand_inputs_to_game_input, merge_inputs

# ── logger ────────────────────────────────────────────────────────────────
logging.basicConfig(
    filename="game.log",
    filemode="a",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Overcook-style pygame game")
    parser.add_argument("-test", action="store_true", help="Use test button labels")
    parser.add_argument("-active", action="store_true", help="Show camera feed")
    parser.add_argument("--gesture", action="store_true",
                        help="Enable gesture recognition input")
    parser.add_argument("--flip", action="store_true", default=True,
                        help="Mirror camera horizontally (default: True)")
    return parser.parse_args()


def main():
    args = _parse_args()

    ui_mode = "normal"
    if args.test:
        ui_mode = "test"
    if args.active or args.gesture:
        ui_mode = "active"

    game = Game(ui_mode=ui_mode, use_gesture=args.gesture, flip=args.flip)
    held = {"left": False, "right": False}
    _gi_frame: dict = {}
    mpressed = False
    station_click = None
    overlay_click = None
    pipeline_frame = None

    _SLOT_KEYS = {
        pygame.K_1: 1, pygame.K_2: 2, pygame.K_3: 3,
        pygame.K_4: 4, pygame.K_5: 5,
    }

    while True:
        dt = min(clock.tick(FPS) / 1000.0, 0.05)
        _gi_frame = {}
        station_click = None
        overlay_click = None
        pipeline_frame = None

        # ── gesture recognition step ──────────────────────────────────
        gesture_gi = GameInput()
        if game.use_gesture:
            hand_inputs, pipeline_frame = game.gesture_step()
            if hand_inputs:
                gesture_gi = hand_inputs_to_game_input(
                    hand_inputs,
                    overlay_active=game.overlay.active,
                )

        # ── pygame event processing ───────────────────────────────────
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                game.shutdown()
                pygame.quit(); sys.exit()
            if event.type == pygame.KEYDOWN:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"] = True
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = True
                if event.key in _SLOT_KEYS and game.state == "play":
                    _gi_frame["move_to_slot"] = _SLOT_KEYS[event.key]
                if event.key in (pygame.K_z, pygame.K_SPACE):
                    if game.state == "play": _gi_frame["confirm"] = True
                    elif game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_c and game.state == "play": _gi_frame["chop"] = True
                if event.key == pygame.K_v and game.state == "play": _gi_frame["stir"] = True
                if event.key == pygame.K_r:
                    if game.state == "play":
                        game.recipe_overlay.active = not game.recipe_overlay.active
                        game.overlay.active = False
                if event.key == pygame.K_RETURN:
                    if game.state in ("title", "over"):
                        game.reset(); game.state = "play"
                        game._spawn_order(); game._spawn_order()
                if event.key == pygame.K_ESCAPE:
                    if game.recipe_overlay.active: game.recipe_overlay.active = False
                    elif game.overlay.active: game.overlay.active = False
                    elif game.state == "play": game.state = "paused"
                    elif game.state == "paused": game.state = "play"
                    else:
                        game.shutdown()
                        pygame.quit(); sys.exit()
            if event.type == pygame.KEYUP:
                if event.key in (pygame.K_LEFT, pygame.K_a): held["left"]  = False
                if event.key in (pygame.K_RIGHT, pygame.K_d): held["right"] = False
            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                mpressed = True
                click_pos = pygame.mouse.get_pos()
                if game.overlay.active: overlay_click = click_pos
                else: station_click = click_pos
            if event.type == pygame.MOUSEBUTTONUP and event.button == 1:
                mpressed = False

        # ── build merged input ────────────────────────────────────────
        move_dir = 0
        if held["left"]:    move_dir = -1
        elif held["right"]: move_dir = 1

        mpos = pygame.mouse.get_pos()
        keyboard_gi = GameInput(
            move_dir     = move_dir,
            move_to_slot = _gi_frame.get("move_to_slot"),
            station_click= station_click,
            confirm      = _gi_frame.get("confirm",  False),
            chop         = _gi_frame.get("chop",     False),
            stir         = _gi_frame.get("stir",     False),
            overlay_click= overlay_click,
        )
        gi = merge_inputs(keyboard_gi, gesture_gi)

        # ── update & draw ─────────────────────────────────────────────
        game.update(dt, gi, mpos, mpressed)

        if game.state == "title": game.draw_title()
        elif game.state == "over": game.draw_over()
        elif game.state == "paused": game.draw_paused()
        else: game.draw(pipeline_frame)

        pygame.display.flip()


if __name__ == "__main__":
    main()
