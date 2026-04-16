C = {
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

INGS = {
    "tomato":   {"label": "Tomato",   "color": (226, 75, 74),  "can_chop": True},
    "carrot":   {"label": "Carrot",   "color": (239,159, 39),  "can_chop": True},
    "onion":    {"label": "Onion",    "color": (175,169,236),  "can_chop": True},
    "mushroom": {"label": "Mushroom", "color": (180,178,169),  "can_chop": True},
    "rice":     {"label": "Rice",     "color": (232,224,208),  "can_chop": False},
}
ING_KEYS = list(INGS.keys())

RECIPES = [
    {"name": "Tomato Soup", "pts": 100, "needs": ["tomato_c","onion_c"], "cook": True,
     "steps": ["CHOP Tomato & Onion", "Add to Stove & Cook"]},
    {"name": "Fried Rice", "pts": 110, "needs": ["rice","tomato_c"], "cook": True,
     "steps": ["Get Rice, CHOP Tomato", "Add both to Stove & Cook"]},
    {"name": "Mushroom Stir-fry", "pts": 90, "needs": ["mushroom_c","onion_c"], "cook": True,
     "steps": ["CHOP Mushroom & Onion", "Add to Stove & Quick Cook"]},
    {"name": "Veg Curry", "pts": 150, "needs": ["carrot_c","onion_c","rice"], "cook": True,
     "steps": ["CHOP Carrot & Onion, Get Rice", "Add all to Stove & Simmer"]},
    {"name": "Carrot Soup", "pts": 80, "needs": ["carrot_c"], "cook": True,
     "steps": ["CHOP Carrot", "Add to Stove & Cook"]},
    {"name": "Rice Bowl", "pts": 95, "needs": ["rice","mushroom_c"], "cook": True,
     "steps": ["Get Rice, CHOP Mushroom", "Add both to Stove & Cook"]},
    {"name": "Veg Salad", "pts": 70, "needs": ["tomato_c","mushroom_c"], "cook": False,
     "steps": ["CHOP Tomato & Mushroom", "Mix & Plate (NO COOK)"]},
]

BURN_TIME  = 8.0
COOK_TIME  = 5.0
CHOP_TIME  = 3.0
ORDER_TIME = 55.0
GAME_TIME  = 120.0
