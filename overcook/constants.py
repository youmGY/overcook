"""Game constants — colours, ingredients, recipes, and timing parameters.

All game-wide configuration values live here. Modules should import
individual names rather than using ``constants.*`` to keep dependencies
explicit.
"""
from __future__ import annotations

from typing import TypedDict

# ── colour palette ────────────────────────────────────────────────────────

Color = tuple[int, int, int]

C: dict[str, Color] = {
    "bg":           (11,  11,  28),
    "tile_a":       (30,  30,  62),
    "tile_b":       (24,  24,  50),
    "ground":       (20,  20,  48),
    "ground_line":  (90,  80, 180),
    "grid":         (38,  34,  90),

    "ing_base":     (42,  24,   8), "ing_top":    (107, 76, 42),
    "chop_base":    (10,  32,  10), "chop_top":   ( 42,160, 90),
    "pot_base":     (26,   8,   8), "pot_off":    ( 51, 51, 51),
    "pot_on":       (160,  35,   0),
    "plate_base":   (10,  10,  42), "plate_top":  ( 46, 46,106),
    "submit_base":  ( 8,  24,   8), "submit_top": ( 29,158,117),
    "trash_base":   (32,   8,   8), "trash_top":  (122, 32, 64),

    "char_body": ( 83, 65,183), "char_dark": (57, 40,137),
    "char_face": (245,214,184), "char_hat":  (38, 33,105),
    "apron":     (224,220,208),

    "white":  (255,255,255), "black":   (  0,  0,  0),
    "yellow": (255,215, 80), "orange":  (239,159, 39),
    "red":    (226, 75, 74), "green":   ( 29,158,117),
    "lime":   (151,196, 89), "gold":    (250,199,117),
    "blue":   (133,183,235), "purple":  (127,119,221),
    "pink":   (212, 83,126), "burn":    (180, 60,  0),

    "hud_bg":    (22, 22, 46), "hud_brd":   (60, 48,137),
    "ord_bg":    (15, 42, 63), "ord_brd":   (55,138,221),
    "ord_urg":   (239,159, 39),

    "ov_bg":     ( 8, 12, 30),
    "ov_card":   (28, 34, 68),
    "ov_sel":    (60, 50,140),
    "ov_border": (80, 70,180),
}


# ── ingredient definitions ────────────────────────────────────────────────

class IngredientInfo(TypedDict):
    """Schema for a single ingredient entry in :data:`INGS`."""
    label: str
    color: Color
    can_chop: bool


INGS: dict[str, IngredientInfo] = {
    "tomato":   {"label": "Tomato",   "color": (226, 75, 74),  "can_chop": True},
    "carrot":   {"label": "Carrot",   "color": (239,159, 39),  "can_chop": True},
    "onion":    {"label": "Onion",    "color": (175,169,236),  "can_chop": True},
    "mushroom": {"label": "Mushroom", "color": (180,178,169),  "can_chop": True},
    "rice":     {"label": "Rice",     "color": (232,224,208),  "can_chop": False},
}

ING_KEYS: list[str] = list(INGS.keys())


# ── recipe definitions ────────────────────────────────────────────────────

class RecipeInfo(TypedDict):
    """Schema for a single recipe entry in :data:`RECIPES`."""
    name: str
    pts: int
    needs: list[str]
    cook: bool
    steps: list[str]


RECIPES: list[RecipeInfo] = [
    {"name": "Tomato Soup", "pts": 100, "needs": ["tomato_c", "onion_c"], "cook": True,
     "steps": ["CHOP Tomato & Onion", "Add to Stove & Cook"]},
    {"name": "Fried Rice", "pts": 110, "needs": ["rice", "tomato_c"], "cook": True,
     "steps": ["Get Rice, CHOP Tomato", "Add both to Stove & Cook"]},
    {"name": "Mushroom Stir-fry", "pts": 90, "needs": ["mushroom_c", "onion_c"], "cook": True,
     "steps": ["CHOP Mushroom & Onion", "Add to Stove & Quick Cook"]},
    {"name": "Veg Curry", "pts": 150, "needs": ["carrot_c", "onion_c", "rice"], "cook": True,
     "steps": ["CHOP Carrot & Onion", "Get Rice", "Add all to Stove & Simmer"]},
    {"name": "Carrot Soup", "pts": 80, "needs": ["carrot_c"], "cook": True,
     "steps": ["CHOP Carrot", "Add to Stove & Cook"]},
]


# ── timing & gameplay constants ───────────────────────────────────────────

BURN_TIME: float = 8.0
"""Seconds after cooking completes before the dish burns."""

COOK_TIME: float = 5.0
"""Legacy constant — retained for test compatibility."""

CHOP_TIME: float = 3.0
"""Time budget for chopping animation (informational)."""

CHOP_ACTIONS: int = 4
"""Number of chop hits required to finish chopping."""

STIR_ACTIONS: int = 5
"""Number of stir actions required to finish cooking."""

ORDER_TIME: float = 55.0
"""Seconds before an order expires."""

GAME_TIME: float = 240.0
"""Total game duration in seconds."""

MAX_ACTIVE_ORDERS: int = 3
"""Maximum number of simultaneous active orders."""

STIR_BURN_EXTRA: int = 3
"""Extra stirs beyond STIR_ACTIONS before the pot burns."""

PROXIMITY_THRESHOLD: int = 110
"""Pixel distance within which a player can interact with a station."""

HUD_HEIGHT: int = 44
"""Height of the top heads-up display bar in pixels."""

SCORE_PENALTY_BURNED: int = 30
"""Score penalty for submitting a burned dish."""

SCORE_PENALTY_EXPIRED: int = 30
"""Score penalty when an order expires."""

ORDER_SPAWN_INTERVAL: float = 15.0
"""Minimum seconds between automatic order spawns."""
