"""
Unit tests for overcook game modules.
Mocks pygame rendering so tests run headless.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

# ─── pygame stub (before any game imports) ─────────────────────────────────
_pygame = types.ModuleType("pygame")

_pygame.init = lambda: None
_pygame.quit = lambda: None
_pygame.SRCALPHA = 0
_pygame.RESIZABLE = 0
_pygame.QUIT = 256
_pygame.KEYDOWN = 768
_pygame.KEYUP = 769
_pygame.MOUSEBUTTONDOWN = 1025
_pygame.MOUSEBUTTONUP = 1026
_pygame.K_LEFT = 276; _pygame.K_RIGHT = 275; _pygame.K_a = 97; _pygame.K_d = 100
_pygame.K_z = 122; _pygame.K_SPACE = 32; _pygame.K_r = 114
_pygame.K_RETURN = 13; _pygame.K_ESCAPE = 27

class _FakeRect:
    def __init__(self, x=0, y=0, w=0, h=0):
        self.x=x; self.y=y; self.w=w; self.h=h
        self.centerx=x+w//2; self.centery=y+h//2
        self.center=(self.centerx, self.centery)
        self.bottom=y+h
    def collidepoint(self, pos): return False
    def __iter__(self): return iter((self.x, self.y, self.w, self.h))

_pygame.Rect = _FakeRect

class _FakeSurface:
    def __init__(self, *a, **kw): pass
    def get_size(self): return (1024, 800)
    def get_width(self): return 0
    def get_height(self): return 0
    def get_rect(self, **kw): return _FakeRect()
    def blit(self, *a, **kw): pass
    def fill(self, *a, **kw): pass
    def set_alpha(self, *a): pass

_pygame.Surface = _FakeSurface

class _FakeFont:
    def render(self, text, aa, color): return _FakeSurface()

class _FakeFontModule:
    def Font(self, path, size): return _FakeFont()
    def SysFont(self, name, size): return _FakeFont()

_pygame.font = _FakeFontModule()

_draw = types.ModuleType("pygame.draw")
_draw.rect = lambda *a, **kw: None
_draw.circle = lambda *a, **kw: None
_draw.line = lambda *a, **kw: None
_draw.ellipse = lambda *a, **kw: None
_draw.polygon = lambda *a, **kw: None
_draw.arc = lambda *a, **kw: None
_pygame.draw = _draw

class _FakeDisplay:
    def set_mode(self, *a, **kw): return _FakeSurface()
    def set_caption(self, *a): pass
    def flip(self): pass

_pygame.display = _FakeDisplay()

class _FakeClock:
    def tick(self, fps=60): return 16
    def get_fps(self): return 60.0

class _FakeTime:
    def Clock(self): return _FakeClock()
    def time(self): return 0.0

_pygame.time = _FakeTime()
_pygame.mouse = MagicMock()
_pygame.mouse.get_pos.return_value = (0, 0)
_pygame.event = MagicMock()
_pygame.event.get.return_value = []

sys.modules["pygame"] = _pygame

# ─── now import game modules ────────────────────────────────────────────────
import constants
from constants import (
    C, INGS, ING_KEYS, RECIPES,
    BURN_TIME, COOK_TIME, CHOP_TIME, ORDER_TIME, GAME_TIME,
    CHOP_ACTIONS, STIR_ACTIONS,
)

import engine
engine.screen = _FakeSurface()
engine.F = {sz: _FakeFont() for sz in (12, 14, 18, 24, 32, 40)}

import utils
from utils import bar

import entities
from entities import Station, Player, Order

import game as game_module
from game import Game, GameInput


# ════════════════════════════════════════════════════════════════════════════
# constants
# ════════════════════════════════════════════════════════════════════════════
class TestConstants(unittest.TestCase):

    def test_ing_keys_match_ings(self):
        self.assertEqual(set(ING_KEYS), set(INGS.keys()))

    def test_rice_cannot_chop(self):
        self.assertFalse(INGS["rice"]["can_chop"])

    def test_all_other_ings_can_chop(self):
        for k, v in INGS.items():
            if k != "rice":
                self.assertTrue(v["can_chop"], f"{k} should be choppable")

    def test_recipes_have_required_fields(self):
        for rec in RECIPES:
            for field in ("name", "pts", "needs", "cook", "steps"):
                self.assertIn(field, rec, f"recipe '{rec['name']}' missing '{field}'")

    def test_veg_salad_cook_false(self):
        salad = next(r for r in RECIPES if r["name"] == "Veg Salad")
        self.assertFalse(salad["cook"])

    def test_timing_constants_positive(self):
        for name, val in [("BURN_TIME", BURN_TIME), ("COOK_TIME", COOK_TIME),
                          ("CHOP_TIME", CHOP_TIME), ("ORDER_TIME", ORDER_TIME),
                          ("GAME_TIME", GAME_TIME)]:
            self.assertGreater(val, 0, f"{name} must be positive")

    def test_needs_chopped_suffix_consistency(self):
        """All chopped needs end with _c; items without _c should exist as raw ings."""
        for rec in RECIPES:
            for need in rec["needs"]:
                base = need.replace("_c", "")
                self.assertIn(base, INGS, f"'{need}' base '{base}' not in INGS")


# ════════════════════════════════════════════════════════════════════════════
# utils.bar
# ════════════════════════════════════════════════════════════════════════════
class FakeSurfaceCapture:
    """Surface that records draw calls via bar."""
    def __init__(self):
        self.calls = []

class TestBar(unittest.TestCase):

    def setUp(self):
        self.drawn = []
        self._orig_rr = utils.rr

        def fake_rr(surf, color, rect, r=6):
            self.drawn.append(rect)

        utils.rr = fake_rr

    def tearDown(self):
        utils.rr = self._orig_rr

    def test_pct_zero_skips_fill(self):
        bar(None, 0, 0, 100, 10, 0.0, (0,0,0), (1,1,1))
        # only bg drawn (1 call)
        self.assertEqual(len(self.drawn), 1)

    def test_pct_one_draws_full_width(self):
        bar(None, 0, 0, 100, 10, 1.0, (0,0,0), (1,1,1), r=3)
        self.assertEqual(len(self.drawn), 2)
        fill_rect = self.drawn[1]
        self.assertEqual(fill_rect[2], 100)  # width == full bar width

    def test_small_pct_minimum_fill_width(self):
        """Fill width must be at least r*2 to avoid border-radius clipping."""
        r = 4
        bar(None, 0, 0, 100, 10, 0.01, (0,0,0), (1,1,1), r=r)
        fill_rect = self.drawn[1]
        self.assertGreaterEqual(fill_rect[2], r * 2)

    def test_pct_greater_than_one_overflows(self):
        """No clamp: caller is responsible. Just verify it doesn't crash."""
        bar(None, 0, 0, 100, 10, 1.5, (0,0,0), (1,1,1))
        self.assertEqual(len(self.drawn), 2)

    def test_negative_pct_skips_fill(self):
        bar(None, 0, 0, 100, 10, -0.5, (0,0,0), (1,1,1))
        self.assertEqual(len(self.drawn), 1)


# ════════════════════════════════════════════════════════════════════════════
# Station
# ════════════════════════════════════════════════════════════════════════════
class TestStationChop(unittest.TestCase):

    def _make_chop(self):
        return Station("chop", 0, 0)

    def _make_item(self, key="tomato"):
        return {"id": key, "label": INGS[key]["label"], "chopped": False}

    def test_no_progress_when_idle(self):
        st = self._make_chop()
        events = st.update(1.0)
        self.assertEqual(events, [])
        self.assertEqual(st.chop_prog, 0.0)

    def test_progress_accumulates(self):
        st = self._make_chop()
        st.chop_item = self._make_item()
        st.chop_hits = max(1, CHOP_ACTIONS // 2)
        st.chopping = True
        st.update(0.0)
        self.assertAlmostEqual(st.chop_prog, st.chop_hits / CHOP_ACTIONS, places=5)

    def test_chop_done_event_emitted(self):
        st = self._make_chop()
        st.chop_item = self._make_item()
        st.chop_hits = CHOP_ACTIONS
        st.chopping = True
        events = st.update(0.0)
        self.assertIn("chop_done", events)

    def test_chop_item_mutated_on_done(self):
        st = self._make_chop()
        item = self._make_item("carrot")
        st.chop_item = item
        st.chop_hits = CHOP_ACTIONS
        st.chopping = True
        st.update(0.0)
        self.assertTrue(st.chop_item["chopped"])
        self.assertTrue(st.chop_item["id"].endswith("_c"))
        self.assertIn("Chopped", st.chop_item["label"])
        self.assertFalse(st.chopping)

    def test_already_chopped_no_progress(self):
        st = self._make_chop()
        item = self._make_item()
        item["chopped"] = True
        item["id"] = "tomato_c"
        st.chop_item = item
        st.chop_hits = CHOP_ACTIONS
        st.chopping = True
        events = st.update(0.0)
        self.assertNotIn("chop_done", events)

    def test_progress_clamped_at_one(self):
        st = self._make_chop()
        st.chop_item = self._make_item()
        st.chop_hits = CHOP_ACTIONS * 10
        st.chopping = True
        st.update(0.0)
        self.assertEqual(st.chop_prog, 1.0)

    def test_zero_dt_no_progress(self):
        st = self._make_chop()
        st.chop_item = self._make_item()
        st.chopping = True
        events = st.update(0.0)
        self.assertEqual(events, [])
        self.assertEqual(st.chop_prog, 0.0)


class TestStationPot(unittest.TestCase):

    def _make_pot(self):
        return Station("pot", 0, 0)

    def _item(self, key="tomato"):
        return {"id": key + "_c", "label": "Chopped " + key, "chopped": True}

    def test_no_progress_when_not_cooking(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        events = st.update(1.0)
        self.assertEqual(events, [])
        self.assertEqual(st.pot_prog, 0.0)

    def test_cook_progress_accumulates(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_stirs = max(1, STIR_ACTIONS // 2)
        st.pot_cooking = True; st.pot_on = True
        st.update(0.0)
        self.assertAlmostEqual(st.pot_prog, st.pot_stirs / STIR_ACTIONS, places=5)

    def test_cook_done_event(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_stirs = STIR_ACTIONS
        st.pot_cooking = True; st.pot_on = True
        events = st.update(0.0)
        self.assertIn("cook_done", events)
        self.assertTrue(st.pot_cooked)
        self.assertFalse(st.pot_cooking)
        self.assertAlmostEqual(st.pot_burn, 0.0)

    def test_burn_timer_starts_after_cooked(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_cooked = True
        st.update(2.0)
        self.assertAlmostEqual(st.pot_burn, 2.0, places=5)

    def test_burned_event_at_threshold(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_cooked = True
        events = st.update(BURN_TIME)
        self.assertIn("burned", events)

    def test_burn_timer_not_started_without_items(self):
        """If pot is cooked but items already removed, burn should not advance."""
        st = self._make_pot()
        st.pot_cooked = True
        st.pot_items = []
        st.update(10.0)
        self.assertAlmostEqual(st.pot_burn, 0.0)

    def test_cook_progress_clamped(self):
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_stirs = STIR_ACTIONS * 10
        st.pot_cooking = True
        st.update(0.0)
        self.assertEqual(st.pot_prog, 1.0)

    def test_no_cook_progress_after_cooked(self):
        """pot_prog should stay at 1.0 once cooked; no further events."""
        st = self._make_pot()
        st.pot_items = [self._item()]
        st.pot_stirs = STIR_ACTIONS
        st.pot_cooking = True
        st.update(0.0)               # cook_done
        events = st.update(1.0)       # should not emit cook_done again
        self.assertNotIn("cook_done", events)


# ════════════════════════════════════════════════════════════════════════════
# Order
# ════════════════════════════════════════════════════════════════════════════
class TestOrder(unittest.TestCase):

    def _recipe(self):
        return RECIPES[0]

    def test_countdown_decrements(self):
        o = Order(self._recipe())
        o.update(10.0)
        self.assertAlmostEqual(o.t, ORDER_TIME - 10.0, places=5)

    def test_t_clamped_at_zero(self):
        o = Order(self._recipe())
        o.update(ORDER_TIME * 10)
        self.assertEqual(o.t, 0.0)

    def test_failed_event_when_expired(self):
        o = Order(self._recipe())
        result = o.update(ORDER_TIME + 1)
        self.assertEqual(result, "failed")
        self.assertEqual(o.status, "failed")

    def test_no_event_before_expiry(self):
        o = Order(self._recipe())
        result = o.update(ORDER_TIME - 1)
        self.assertIsNone(result)
        self.assertEqual(o.status, "active")

    def test_no_update_on_failed(self):
        o = Order(self._recipe())
        o.status = "failed"
        o.t = 0.0
        result = o.update(5.0)
        self.assertIsNone(result)

    def test_no_update_on_done(self):
        o = Order(self._recipe())
        o.status = "done"
        result = o.update(5.0)
        self.assertIsNone(result)

    def test_failed_only_once(self):
        """Second update on an already-failed order returns None."""
        o = Order(self._recipe())
        o.update(ORDER_TIME + 1)
        result = o.update(1.0)
        self.assertIsNone(result)

    def test_unique_ids(self):
        a = Order(self._recipe())
        b = Order(self._recipe())
        self.assertNotEqual(a.id, b.id)

    def test_id_monotonically_increases(self):
        a = Order(self._recipe())
        b = Order(self._recipe())
        self.assertGreater(b.id, a.id)


# ════════════════════════════════════════════════════════════════════════════
# Player
# ════════════════════════════════════════════════════════════════════════════
class TestPlayer(unittest.TestCase):

    GW, GY = 1024, 600

    def _player(self, x=200, y=500):
        return Player(x, y)

    def test_moves_right(self):
        p = self._player()
        x0 = p.x
        p.update(1, 0.1, self.GW, self.GY)
        self.assertGreater(p.x, x0)

    def test_moves_left(self):
        p = self._player()
        x0 = p.x
        p.update(-1, 0.1, self.GW, self.GY)
        self.assertLess(p.x, x0)

    def test_stops_immediately_on_no_input(self):
        p = self._player()
        p.update(1, 0.1, self.GW, self.GY)   # build velocity
        p.update(0, 0.1, self.GW, self.GY)   # release
        self.assertEqual(p.vx, 0.0)

    def test_facing_follows_direction(self):
        p = self._player()
        p.update(1, 0.1, self.GW, self.GY)
        self.assertEqual(p.facing, 1)
        p.update(-1, 0.1, self.GW, self.GY)
        self.assertEqual(p.facing, -1)

    def test_clamped_at_right_wall(self):
        p = self._player(x=self.GW - 5)
        p.update(1, 1.0, self.GW, self.GY)
        self.assertLessEqual(p.x, self.GW - Player.PW - 4)

    def test_clamped_at_left_wall(self):
        p = self._player(x=0)
        p.update(-1, 1.0, self.GW, self.GY)
        self.assertGreaterEqual(p.x, 4)

    def test_falls_to_ground(self):
        p = self._player(x=200, y=0)
        for _ in range(30):
            p.update(0, 0.05, self.GW, self.GY)
        self.assertAlmostEqual(p.y, self.GY - Player.PH, places=1)
        self.assertEqual(p.vy, 0.0)

    def test_walk_t_only_advances_when_moving(self):
        p = self._player()
        t0 = p.walk_t
        p.update(0, 0.1, self.GW, self.GY)
        self.assertEqual(p.walk_t, t0)
        p.update(1, 0.1, self.GW, self.GY)
        self.assertGreater(p.walk_t, t0)


# ════════════════════════════════════════════════════════════════════════════
# Game helpers
# ════════════════════════════════════════════════════════════════════════════
class TestGameNear(unittest.TestCase):

    def setUp(self):
        engine.screen = _FakeSurface()
        self.g = Game()
        self.g.state = "play"

    def test_returns_none_when_no_station_nearby(self):
        self.g.player.x = 9999
        self.g.player.y = 9999
        self.assertIsNone(self.g._near())

    def test_returns_nearest_station(self):
        st = self.g.stations[0]
        cx, cy = st.cx(), st.cy()
        self.g.player.x = cx - Player.PW // 2
        self.g.player.y = cy - Player.PH // 2
        result = self.g._near()
        self.assertIs(result, st)

    def test_strict_less_than_110(self):
        """Player at >110 from all stations should return None."""
        # place player far to the left of all stations
        self.g.player.x = -500
        self.g.player.y = -500
        result = self.g._near()
        self.assertIsNone(result)


# ════════════════════════════════════════════════════════════════════════════
# Game._spawn_order
# ════════════════════════════════════════════════════════════════════════════
class TestSpawnOrder(unittest.TestCase):

    def setUp(self):
        engine.screen = _FakeSurface()
        self.g = Game()
        self.g.state = "play"
        self.g.orders = []

    def test_spawns_up_to_three(self):
        for _ in range(5):
            self.g._spawn_order()
        active = sum(1 for o in self.g.orders if o.status == "active")
        self.assertEqual(active, 3)

    def test_does_not_count_done_orders(self):
        for _ in range(3):
            self.g._spawn_order()
        self.g.orders[0].status = "done"
        self.g._spawn_order()
        active = sum(1 for o in self.g.orders if o.status == "active")
        self.assertEqual(active, 3)

    def test_does_not_count_failed_orders(self):
        for _ in range(3):
            self.g._spawn_order()
        self.g.orders[0].status = "failed"
        self.g._spawn_order()
        active = sum(1 for o in self.g.orders if o.status == "active")
        self.assertEqual(active, 3)

    def test_spawns_valid_recipe(self):
        self.g._spawn_order()
        self.assertIn(self.g.orders[0].recipe, RECIPES)


# ════════════════════════════════════════════════════════════════════════════
# Game.do_action — pantry
# ════════════════════════════════════════════════════════════════════════════
class TestDoActionPantry(unittest.TestCase):

    def _setup(self):
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        pantry = next(s for s in g.stations if s.kind == "ing")
        return g, pantry

    def test_opens_overlay_when_empty_handed(self):
        g, pantry = self._setup()
        g.player.x = pantry.cx() - Player.PW // 2
        g.player.y = pantry.cy() - Player.PH // 2 - 5
        g.player.holding = None
        g.do_action()
        self.assertTrue(g.overlay.active)

    def test_shows_popup_when_holding(self):
        g, pantry = self._setup()
        g.player.x = pantry.cx() - Player.PW // 2
        g.player.y = pantry.cy() - Player.PH // 2 - 5
        g.player.holding = {"id": "tomato", "label": "Tomato", "chopped": False}
        g.do_action()
        self.assertFalse(g.overlay.active)
        self.assertTrue(any("Drop" in p.msg for p in g.popups))


# ════════════════════════════════════════════════════════════════════════════
# Game.do_action — chop board
# ════════════════════════════════════════════════════════════════════════════
class _ChopHelper:
    def setup(self):
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        chop = next(s for s in g.stations if s.kind == "chop")
        # position player near chop station
        g.player.x = chop.cx() - Player.PW // 2
        g.player.y = chop.cy() - Player.PH // 2 - 5
        return g, chop

class TestDoActionChop(unittest.TestCase, _ChopHelper):

    def test_place_item_starts_chopping(self):
        g, chop = self.setup()
        g.player.holding = {"id": "tomato", "label": "Tomato", "chopped": False}
        g.do_action()
        self.assertIsNotNone(chop.chop_item)
        self.assertTrue(chop.chopping)
        self.assertIsNone(g.player.holding)

    def test_cannot_place_already_chopped_item(self):
        g, chop = self.setup()
        g.player.holding = {"id": "tomato_c", "label": "Chopped Tomato", "chopped": True}
        g.do_action()
        # should show popup, not place
        self.assertTrue(any("Already" in p.msg for p in g.popups))
        self.assertIsNone(chop.chop_item)

    def test_cannot_chop_rice(self):
        g, chop = self.setup()
        g.player.holding = {"id": "rice", "label": "Rice", "chopped": False}
        g.do_action()
        self.assertTrue(any("chop" in p.msg.lower() for p in g.popups))
        self.assertIsNone(chop.chop_item)

    def test_pickup_chopped_item_when_empty_handed(self):
        g, chop = self.setup()
        chop.chop_item = {"id": "tomato_c", "label": "Chopped Tomato", "chopped": True}
        chop.chopping = False
        g.player.holding = None
        g.do_action()
        self.assertIsNotNone(g.player.holding)
        self.assertTrue(g.player.holding["chopped"])
        self.assertIsNone(chop.chop_item)

    def test_cannot_pickup_mid_chop_when_holding(self):
        """Player holding something, board is mid-chop -> show wait popup."""
        g, chop = self.setup()
        chop.chop_item = {"id": "carrot", "label": "Carrot", "chopped": False}
        chop.chopping = True
        g.player.holding = {"id": "onion", "label": "Onion", "chopped": False}
        g.do_action()
        self.assertTrue(any("Wait" in p.msg for p in g.popups))

    def test_resume_chopping_empty_handed(self):
        g, chop = self.setup()
        chop.chop_item = {"id": "onion", "label": "Onion", "chopped": False}
        chop.chopping = False
        g.player.holding = None
        g.do_action()
        self.assertTrue(chop.chopping)


# ════════════════════════════════════════════════════════════════════════════
# Game.do_action — pot
# ════════════════════════════════════════════════════════════════════════════
class TestDoActionPot(unittest.TestCase):

    def _setup(self):
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        pot = next(s for s in g.stations if s.kind == "pot")
        g.player.x = pot.cx() - Player.PW // 2
        g.player.y = pot.cy() - Player.PH // 2 - 5
        return g, pot

    def test_add_ingredient_to_pot(self):
        g, pot = self._setup()
        item = {"id": "tomato_c", "label": "Chopped Tomato", "chopped": True}
        g.player.holding = item
        g.do_action()
        self.assertEqual(len(pot.pot_items), 1)
        self.assertIsNone(g.player.holding)

    def test_start_cooking(self):
        g, pot = self._setup()
        pot.pot_items = [{"id": "tomato_c", "label": "Chopped Tomato", "chopped": True}]
        g.player.holding = None
        g.do_action()
        self.assertTrue(pot.pot_cooking)
        self.assertTrue(pot.pot_on)

    def test_cannot_start_cooking_empty_pot(self):
        g, pot = self._setup()
        pot.pot_items = []
        g.player.holding = None
        g.do_action()
        self.assertFalse(pot.pot_cooking)

    def test_pickup_cooked_dish(self):
        g, pot = self._setup()
        pot.pot_items = [{"id": "tomato_c", "chopped": True}]
        pot.pot_cooked = True
        g.player.holding = None
        g.do_action()
        self.assertIsNotNone(g.player.holding)
        self.assertTrue(g.player.holding.get("cooked"))
        self.assertEqual(pot.pot_items, [])
        self.assertFalse(pot.pot_cooked)
        self.assertFalse(pot.pot_on)

    def test_clear_burned_food(self):
        g, pot = self._setup()
        pot.pot_items = [{"id": "tomato_c", "chopped": True}]
        pot.pot_cooked = True
        pot.pot_burn = BURN_TIME + 1
        g.player.holding = None
        g.do_action()
        self.assertEqual(pot.pot_items, [])
        self.assertFalse(pot.pot_cooked)
        self.assertIsNone(g.player.holding)  # nothing given to player

    def test_silently_blocked_when_holding_and_pot_cooked(self):
        """Holding item + pot already cooked: no branch matches, no popup about it."""
        g, pot = self._setup()
        pot.pot_items = [{"id": "tomato_c", "chopped": True}]
        pot.pot_cooked = True
        g.player.holding = {"id": "onion_c", "chopped": True}
        popups_before = len(g.popups)
        g.do_action()
        # Nothing changes at the pot
        self.assertEqual(len(pot.pot_items), 1)
        self.assertTrue(pot.pot_cooked)

    def test_multiple_ingredients_can_be_added(self):
        g, pot = self._setup()
        for key in ["tomato_c", "onion_c", "carrot_c"]:
            g.player.holding = {"id": key, "chopped": True}
            g.do_action()
        self.assertEqual(len(pot.pot_items), 3)


# ════════════════════════════════════════════════════════════════════════════
# Game.do_action — submit station  (plate station removed: submit directly from hand)
# ════════════════════════════════════════════════════════════════════════════
class TestDoActionSubmit(unittest.TestCase):

    def _setup(self):
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        submit = next(s for s in g.stations if s.kind == "submit")
        g.player.x = submit.cx() - Player.PW // 2
        g.player.y = submit.cy() - Player.PH // 2 - 5
        g.orders = []
        return g, submit

    def _cooked_dish(self, needs):
        contents = [{"id": n, "chopped": n.endswith("_c")} for n in needs]
        return {"id": "cooked", "label": "Cooked Dish", "contents": contents, "cooked": True}

    def test_submit_matched_order(self):
        g, submit = self._setup()
        rec = next(r for r in RECIPES if r["name"] == "Tomato Soup")
        order = Order(rec); order.t = ORDER_TIME
        g.orders = [order]
        g.player.holding = self._cooked_dish(rec["needs"])
        initial_score = g.score
        g.do_action()
        self.assertEqual(order.status, "done")
        self.assertIsNone(g.player.holding)
        self.assertGreater(g.score, initial_score)

    def test_submit_includes_time_bonus(self):
        g, submit = self._setup()
        rec = next(r for r in RECIPES if r["name"] == "Tomato Soup")
        order = Order(rec); order.t = ORDER_TIME
        g.orders = [order]
        g.player.holding = self._cooked_dish(rec["needs"])
        g.do_action()
        self.assertEqual(g.score, rec["pts"] + 50)

    def test_submit_no_match_clears_holding(self):
        g, submit = self._setup()
        g.orders = []
        g.player.holding = self._cooked_dish(["tomato_c", "onion_c"])
        g.do_action()
        self.assertIsNone(g.player.holding)
        self.assertTrue(any("No matching" in p.msg for p in g.popups))

    def test_submit_nothing_popup(self):
        g, submit = self._setup()
        g.player.holding = None
        g.do_action()
        self.assertTrue(any("Nothing" in p.msg or "submit" in p.msg.lower() for p in g.popups))

    def test_submit_missing_ingredient_id_clears_holding(self):
        g, submit = self._setup()
        g.player.holding = {
            "id": "cooked",
            "label": "Cooked Dish",
            "contents": [{"chopped": True}],
            "cooked": True,
        }
        g.do_action()
        self.assertIsNone(g.player.holding)
        self.assertTrue(any("missing ingredient id" in p.msg.lower() for p in g.popups))

    def test_submit_matches_first_active_order(self):
        g, submit = self._setup()
        rec = next(r for r in RECIPES if r["name"] == "Tomato Soup")
        o1 = Order(rec); o2 = Order(rec)
        g.orders = [o1, o2]
        g.player.holding = self._cooked_dish(rec["needs"])
        g.do_action()
        self.assertEqual(o1.status, "done")
        self.assertEqual(o2.status, "active")

    def test_submit_burned_dish_rejected(self):
        g, submit = self._setup()
        g.player.holding = {"id": "cooked", "cooked": True, "burned": True, "contents": []}
        g.do_action()
        self.assertTrue(any("Nothing" in p.msg or "submit" in p.msg.lower() for p in g.popups))


# ════════════════════════════════════════════════════════════════════════════
# Game.do_action — trash
# ════════════════════════════════════════════════════════════════════════════
class TestDoActionTrash(unittest.TestCase):

    def _setup(self):
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        trash = next(s for s in g.stations if s.kind == "trash")
        g.player.x = trash.cx() - Player.PW // 2
        g.player.y = trash.cy() - Player.PH // 2 - 5
        return g, trash

    def test_discards_held_item(self):
        g, trash = self._setup()
        g.player.holding = {"id": "tomato", "label": "Tomato", "chopped": False}
        g.do_action()
        self.assertIsNone(g.player.holding)
        self.assertTrue(any("Trash" in p.msg for p in g.popups))

    def test_clears_chop_board_when_empty_handed(self):
        g, trash = self._setup()
        chop = next(s for s in g.stations if s.kind == "chop")
        chop.chop_item = {"id": "onion", "label": "Onion", "chopped": False}
        g.player.holding = None
        g.do_action()
        self.assertIsNone(chop.chop_item)

    def test_clears_all_chop_boards(self):
        g, trash = self._setup()
        for chop in [s for s in g.stations if s.kind == "chop"]:
            chop.chop_item = {"id": "onion", "label": "Onion", "chopped": False}
        g.player.holding = None
        g.do_action()
        for chop in [s for s in g.stations if s.kind == "chop"]:
            self.assertIsNone(chop.chop_item)

    def test_popup_when_nothing_to_trash(self):
        g, trash = self._setup()
        chop = next(s for s in g.stations if s.kind == "chop")
        chop.chop_item = None
        g.player.holding = None
        g.do_action()
        self.assertTrue(any("Nothing" in p.msg for p in g.popups))

    def test_can_trash_burned_item(self):
        g, trash = self._setup()
        g.player.holding = {"id": "cooked", "cooked": True, "burned": True, "contents": []}
        g.do_action()
        self.assertIsNone(g.player.holding)


# ════════════════════════════════════════════════════════════════════════════
# Game score / timer
# ════════════════════════════════════════════════════════════════════════════
class TestGameScoreAndTimer(unittest.TestCase):

    def setUp(self):
        engine.screen = _FakeSurface()
        self.g = Game()
        self.g.state = "play"
        self.g.orders = []

    def _noop_update(self, dt):
        """Drive update without player/button input."""
        self.g.update(dt, GameInput(), (0, 0), False)

    def test_score_does_not_go_negative_on_fail(self):
        self.g.score = 10
        o = Order(RECIPES[0])
        self.g.orders = [o]
        o.status = "failed"
        self._noop_update(0.016)
        self.assertGreaterEqual(self.g.score, 0)

    def test_timer_decrements(self):
        t0 = self.g.timer
        self._noop_update(5.0)
        self.assertLess(self.g.timer, t0)

    def test_timer_clamped_at_zero(self):
        self.g.timer = 0.1
        self._noop_update(1.0)
        self.assertEqual(self.g.timer, 0.0)

    def test_state_over_when_timer_expires(self):
        self.g.timer = 0.01
        self._noop_update(1.0)
        self.assertEqual(self.g.state, "over")

    def test_initial_two_orders_on_reset(self):
        self.g.reset()
        self.g._spawn_order()
        self.g._spawn_order()
        active = sum(1 for o in self.g.orders if o.status == "active")
        self.assertEqual(active, 2)

    def test_auto_spawn_not_immediate(self):
        """next_order starts at 15.0, so no extra spawn at t=0."""
        self.g.reset()
        self.g.state = "play"
        count_before = len(self.g.orders)
        self._noop_update(0.016)
        self.assertEqual(len(self.g.orders), count_before)

    def test_popups_expire(self):
        for _ in range(5):
            self.g._pop(100, 100, "test", (255, 255, 255))
        # run enough frames to expire all popups (life=80 ticks)
        for _ in range(90):
            for p in self.g.popups:
                p.update()
            self.g.popups = [p for p in self.g.popups if not p.dead]
        self.assertEqual(len(self.g.popups), 0)


# ════════════════════════════════════════════════════════════════════════════
# Veg Salad corner case (cook=False → raw dish cannot be submitted)
# ════════════════════════════════════════════════════════════════════════════
class TestVegSaladUnsubmittable(unittest.TestCase):

    def test_raw_dish_cannot_be_submitted(self):
        """_find_submit_dish() requires cooked=True, so a raw dish is rejected."""
        engine.screen = _FakeSurface()
        g = Game()
        g.state = "play"
        submit = next(s for s in g.stations if s.kind == "submit")
        g.player.x = submit.cx() - Player.PW // 2
        g.player.y = submit.cy() - Player.PH // 2 - 5
        raw_salad = {
            "id": "raw_salad",
            "label": "Raw Salad",
            "contents": [{"id": "tomato_c"}, {"id": "mushroom_c"}],
            "cooked": False,
        }
        g.player.holding = raw_salad
        g.do_action()
        self.assertTrue(any("Nothing" in p.msg or "submit" in p.msg.lower() for p in g.popups))


if __name__ == "__main__":
    unittest.main(verbosity=2)
