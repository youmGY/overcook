# game.py 수정 가이드
# 아래 diff 형식으로 변경할 부분만 표시합니다.

# ─────────────────────────────────────────────────────────────────
# 1. 파일 상단 import에 추가
# ─────────────────────────────────────────────────────────────────

# 기존:
from ui import Popup, Btn, RecipeOverlay, IngredientOverlay

# 변경 후:
from ui import Popup, Btn, RecipeOverlay, IngredientOverlay
from assets import draw_ing_icon, load_ing_icon        # ← 추가


# ─────────────────────────────────────────────────────────────────
# 2. _draw_recipes_panel() 안의 dot 그리는 부분
# ─────────────────────────────────────────────────────────────────

# 기존 (~line 370):
            dot_x = cx_ + 4
            for j, need in enumerate(rec["needs"]):
                base = need.replace("_c", "")
                ing  = INGS.get(base, {})
                col_dot = ing.get("color", (150, 150, 150))
                r_dot = 5
                dy = inner_y + r_dot
                if dot_x + r_dot * 2 + 2 > cx_ + card_w - 4:
                    break
                pygame.draw.circle(screen, col_dot, (dot_x + r_dot, dy), r_dot)
                dot_x += r_dot * 2 + 6
            inner_y += 14

# 변경 후:
            dot_x = cx_ + 4
            ICON_S = 20   # 레시피 패널 안 작은 아이콘 크기
            for j, need in enumerate(rec["needs"]):
                base = need.replace("_c", "")
                ing  = INGS.get(base, {})
                col_dot = ing.get("color", (150, 150, 150))
                dy = inner_y + ICON_S // 2
                if dot_x + ICON_S + 2 > cx_ + card_w - 4:
                    break
                # 아이콘 시도, 없으면 색 원 폴백
                if not draw_ing_icon(screen, base, dot_x + ICON_S//2, dy, ICON_S):
                    pygame.draw.circle(screen, col_dot, (dot_x + ICON_S//2, dy), ICON_S//2)
                dot_x += ICON_S + 4
            inner_y += ICON_S + 2


# ─────────────────────────────────────────────────────────────────
# 3. IngredientOverlay.draw() 안 — 카드별 아이콘 그리기
#    ui.py 수정 (IngredientOverlay 클래스)
# ─────────────────────────────────────────────────────────────────

# ui.py의 IngredientOverlay.draw() 에서 각 재료 카드를 그릴 때:
# 기존 (색 원 또는 텍스트만):
#   pygame.draw.circle(screen, ing["color"], (card_cx, icon_y), 16)

# 변경 후 (아이콘 우선, 폴백 유지):
#   if not draw_ing_icon(screen, key, card_cx, icon_y, 40):
#       pygame.draw.circle(screen, ing.get("color",(150,150,150)), (card_cx, icon_y), 16)

# ui.py 상단에도 추가:
# from assets import draw_ing_icon


# ─────────────────────────────────────────────────────────────────
# 4. Player.draw() — holding 아이템 아이콘
#    entities.py 수정 (Player 클래스)
# ─────────────────────────────────────────────────────────────────

# entities.py의 Player.draw() 안에서 holding 표시 부분:
# 기존:
#   col = INGS.get(h_id, {}).get("color", (200,200,200))
#   pygame.draw.circle(screen, col, (px + PW//2, py - 10), 8)

# 변경 후:
#   from assets import draw_ing_icon
#   key = h.get("id","")
#   if h.get("chopped"): key = key + "_c"
#   if h.get("cooked"):  key = "cooked_dish"
#   if h.get("burned"):  key = "burned_dish"
#   if not draw_ing_icon(screen, key, px + PW//2, py - 12, 28):
#       col = INGS.get(h.get("id","").replace("_c",""), {}).get("color", (200,200,200))
#       pygame.draw.circle(screen, col, (px + PW//2, py - 10), 8)


# ─────────────────────────────────────────────────────────────────
# 5. Station.draw() — chop_item, pot_items 아이콘
#    entities.py 수정 (Station 클래스)
# ─────────────────────────────────────────────────────────────────

# chop board 위에 재료 표시:
# 기존:
#   col = INGS.get(chop_id, {}).get("color", (200,200,200))
#   pygame.draw.circle(screen, col, (self.cx(), self.y + SH//2), 10)

# 변경 후:
#   chop_key = self.chop_item.get("id","")
#   if self.chop_item.get("chopped"): chop_key += "_c"
#   if not draw_ing_icon(screen, chop_key, self.cx(), self.y + SH//2, 32):
#       col = INGS.get(chop_key.replace("_c",""), {}).get("color", (200,200,200))
#       pygame.draw.circle(screen, col, (self.cx(), self.y + SH//2), 10)

# pot 위 재료들 (여러 개):
# 기존:
#   for i, item in enumerate(self.pot_items):
#       col = INGS.get(item.get("id",""), {}).get("color", (200,200,200))
#       pygame.draw.circle(screen, col, (self.cx() - 10 + i*10, self.y + 10), 5)

# 변경 후:
#   for i, item in enumerate(self.pot_items[:4]):   # 최대 4개 표시
#       ix = self.cx() - 20 + i * 14
#       iy = self.y + 12
#       key = item.get("id","")
#       if item.get("chopped"): key += "_c"
#       if not draw_ing_icon(screen, key, ix, iy, 20):
#           col = INGS.get(key.replace("_c",""), {}).get("color",(200,200,200))
#           pygame.draw.circle(screen, col, (ix, iy), 5)
