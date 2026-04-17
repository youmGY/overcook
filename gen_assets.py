#!/usr/bin/env python3
"""
픽셀아트 식재료 아이콘 생성기
참고 스타일: FOOD_WL/NL.png — 검은 아웃라인 + 하이라이트 + 그림자
출력: assets/ingredients/{name}.png  (48x48 RGBA)
"""

import struct, zlib, os, math

os.makedirs("assets/ingredients", exist_ok=True)

SIZE = 48
BLACK = (20, 15, 15, 255)

# ── PNG writer ────────────────────────────────────────────────────────────────
def _chunk(tag, data):
    c = struct.pack(">I", len(data)) + tag + data
    return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

def write_png(path, pixels):
    H = len(pixels); W = len(pixels[0])
    raw = b""
    for row in pixels:
        raw += b"\x00"
        for p in row:
            raw += bytes([p[0], p[1], p[2], p[3]])
    ihdr = struct.pack(">II", W, H) + bytes([8, 6, 0, 0, 0])
    png  = b"\x89PNG\r\n\x1a\n"
    png += _chunk(b"IHDR", ihdr)
    png += _chunk(b"IDAT", zlib.compress(raw, 9))
    png += _chunk(b"IEND", b"")
    with open(path, "wb") as f:
        f.write(png)

# ── Canvas primitives ─────────────────────────────────────────────────────────
def blank():
    return [[list((0,0,0,0)) for _ in range(SIZE)] for _ in range(SIZE)]

def _blend(canvas, x, y, color):
    if not (0 <= x < SIZE and 0 <= y < SIZE): return
    r,g,b,a = color
    br,bg_,bb,ba = canvas[y][x]
    fa = a/255.0
    canvas[y][x] = [
        int(r*fa + br*(1-fa)),
        int(g*fa + bg_*(1-fa)),
        int(b*fa + bb*(1-fa)),
        min(255, ba + int(a*(1-ba/255.0))),
    ]

def px(canvas, x, y, color):
    _blend(canvas, x, y, color)

def fill_circle(canvas, cx, cy, r, color):
    for y in range(max(0,cy-r-1), min(SIZE,cy+r+2)):
        for x in range(max(0,cx-r-1), min(SIZE,cx+r+2)):
            if (x-cx)**2+(y-cy)**2 <= r*r:
                px(canvas,x,y,color)

def fill_ellipse(canvas, cx, cy, rx, ry, color):
    if rx<=0 or ry<=0: return
    for y in range(max(0,cy-ry-1), min(SIZE,cy+ry+2)):
        for x in range(max(0,cx-rx-1), min(SIZE,cx+rx+2)):
            if ((x-cx)/rx)**2+((y-cy)/ry)**2<=1.0:
                px(canvas,x,y,color)

def fill_rect(canvas, x0, y0, x1, y1, color):
    for y in range(max(0,y0), min(SIZE,y1+1)):
        for x in range(max(0,x0), min(SIZE,x1+1)):
            px(canvas,x,y,color)

def fill_poly(canvas, pts, color):
    if len(pts)<3: return
    miny=max(0,min(p[1] for p in pts))
    maxy=min(SIZE-1,max(p[1] for p in pts))
    n=len(pts)
    for y in range(miny,maxy+1):
        xs=[]
        for i in range(n):
            x0,y0=pts[i]; x1,y1=pts[(i+1)%n]
            if (y0<=y<y1) or (y1<=y<y0):
                if y1!=y0: xs.append(int(x0+(y-y0)*(x1-x0)/(y1-y0)))
        xs.sort()
        for i in range(0,len(xs)-1,2):
            fill_rect(canvas,xs[i],y,xs[i+1],y,color)

def outline_circle(canvas, cx, cy, r, color, thick=1):
    for y in range(max(0,cy-r-2), min(SIZE,cy+r+3)):
        for x in range(max(0,cx-r-2), min(SIZE,cx+r+3)):
            d=math.sqrt((x-cx)**2+(y-cy)**2)
            if r-thick<d<=r+0.5:
                px(canvas,x,y,color)

def outline_ellipse(canvas, cx, cy, rx, ry, color, thick=1):
    if rx<=0 or ry<=0: return
    for y in range(max(0,cy-ry-2), min(SIZE,cy+ry+3)):
        for x in range(max(0,cx-rx-2), min(SIZE,cx+rx+3)):
            d=((x-cx)/rx)**2+((y-cy)/ry)**2
            lo=(1-thick/min(rx,ry))**2; hi=(1+0.6/min(rx,ry))**2
            if lo<d<=hi:
                px(canvas,x,y,color)

def line(canvas, x0,y0,x1,y1, color, w=1):
    dx=abs(x1-x0); dy=abs(y1-y0)
    sx=1 if x0<x1 else -1; sy=1 if y0<y1 else -1
    err=dx-dy
    while True:
        for dw in range(-(w//2),w//2+1):
            px(canvas,x0+dw,y0,color); px(canvas,x0,y0+dw,color)
        if x0==x1 and y0==y1: break
        e2=2*err
        if e2>-dy: err-=dy; x0+=sx
        if e2< dx: err+=dx; y0+=sy

def shade(color, f):
    r,g,b,a=color
    return (min(255,max(0,int(r*f))), min(255,max(0,int(g*f))), min(255,max(0,int(b*f))), a)

def save(canvas, name):
    pixels=[[(c[0],c[1],c[2],c[3]) for c in row] for row in canvas]
    write_png(f"assets/ingredients/{name}.png", pixels)
    print(f"  {name}.png")

# ── Shared pixel-art shading ──────────────────────────────────────────────────
def pa_circle(canvas, cx, cy, r, base):
    """Pixel-art shaded circle: base fill + shadow(BR) + highlight(TL) + outline."""
    shad = shade(base,0.60)
    hi   = shade(base,1.42)
    fill_circle(canvas, cx, cy, r, base)
    # shadow half (bottom-right)
    for y in range(cy, cy+r+1):
        for x in range(cx-r//4, cx+r+1):
            if (x-cx)**2+(y-cy)**2 <= (r-1)**2:
                px(canvas,x,y,shad)
    # highlight spot (top-left)
    fill_circle(canvas, cx-r//3, cy-r//3, max(1,r//3), hi)
    fill_circle(canvas, cx-r//4, cy-r//4, max(1,r//5), (255,255,255,150))
    outline_circle(canvas, cx, cy, r, BLACK)

def pa_ellipse(canvas, cx, cy, rx, ry, base):
    shad=shade(base,0.60); hi=shade(base,1.42)
    fill_ellipse(canvas,cx,cy,rx,ry,base)
    for y in range(cy,cy+ry+1):
        for x in range(cx-rx//4, cx+rx+1):
            if ((x-cx)/max(1,rx))**2+((y-cy)/max(1,ry))**2<=(0.92)**2:
                px(canvas,x,y,shad)
    fill_ellipse(canvas,cx-rx//3,cy-ry//3,max(1,rx//3),max(1,ry//3),hi)
    fill_ellipse(canvas,cx-rx//4,cy-ry//4,max(1,rx//5),max(1,ry//5),(255,255,255,140))
    outline_ellipse(canvas,cx,cy,rx,ry,BLACK)

# ─────────────────────────────────────────────────────────────────────────────
#  재료들
# ─────────────────────────────────────────────────────────────────────────────

def draw_tomato():
    c=blank()
    B=(210,45,45,255)
    pa_circle(c,24,27,17,B)
    fill_circle(c,24,11,3,shade(B,0.7))
    fill_rect(c,22,7,25,13,(50,145,40,255))
    for dx,ty in [(-5,11),(5,11),(-2,8),(2,8)]:
        fill_ellipse(c,24+dx,ty,4,3,(70,175,50,255))
        outline_ellipse(c,24+dx,ty,4,3,BLACK)
    outline_circle(c,24,27,17,BLACK)
    save(c,"tomato")

def draw_onion():
    c=blank()
    B=(185,95,145,255)
    pa_ellipse(c,24,28,17,15,B)
    fill_ellipse(c,24,30,11,9,shade(B,1.12))
    fill_ellipse(c,24,32, 6, 5,shade(B,1.22))
    fill_ellipse(c,24,15, 5, 7,shade(B,0.82))
    outline_ellipse(c,24,28,17,15,BLACK)
    fill_rect(c,22,5,25,14,(70,165,55,255))
    fill_circle(c,23,5,3,(80,185,60,255))
    fill_circle(c,26,4,2,(80,185,60,255))
    line(c,22,5,22,14,BLACK); line(c,25,5,25,14,BLACK)
    save(c,"onion")

def draw_carrot():
    c=blank()
    B=(235,120,30,255)
    body=[(17,14),(31,14),(28,44),(24,47),(20,44)]
    fill_poly(c,body,B)
    fill_poly(c,[(24,14),(31,14),(28,44),(24,47)],shade(B,0.70))
    fill_poly(c,[(17,14),(24,14),(20,42)],shade(B,1.30))
    for y in [22,29,36]:
        w=max(2,int(8-(y-14)*0.15))
        line(c,24-w,y,24+w,y,shade(B,0.58),1)
    tops=[(-5,12,5,8),(0,8,4,9),(5,11,4,8),(-3,7,3,7),(3,7,3,7)]
    for dx,ty,lx,ly in tops:
        fill_ellipse(c,24+dx,ty,lx//2+1,ly//2+1,(65,170,52,255))
        outline_ellipse(c,24+dx,ty,lx//2+1,ly//2+1,BLACK)
    for i in range(len(body)):
        x0,y0=body[i]; x1,y1=body[(i+1)%len(body)]
        line(c,x0,y0,x1,y1,BLACK)
    save(c,"carrot")

def draw_mushroom():
    c=blank()
    CAP=(155,85,45,255); STEM=(230,210,175,255)
    fill_rect(c,18,32,29,43,STEM)
    fill_rect(c,20,32,27,43,shade(STEM,1.1))
    fill_rect(c,28,34,30,42,shade(STEM,0.8))
    fill_rect(c,16,38,30,39,shade(STEM,0.78))
    pa_ellipse(c,24,26,19,13,CAP)
    for sx,sy,sr in [(20,22,3),(31,20,2),(26,18,2),(15,27,2)]:
        fill_circle(c,sx,sy,sr,(220,200,160,210))
        outline_circle(c,sx,sy,sr,shade(CAP,0.45),1)
    outline_ellipse(c,24,26,19,13,BLACK)
    for yy in [32,43]: line(c,18,yy,29,yy,BLACK)
    line(c,18,32,18,43,BLACK); line(c,29,32,29,43,BLACK)
    save(c,"mushroom")

def draw_potato():
    c=blank()
    B=(185,140,75,255)
    fill_ellipse(c,24,26,18,14,B)
    fill_ellipse(c,22,24,16,12,shade(B,1.22))
    fill_ellipse(c,28,30,10, 8,shade(B,0.70))
    for bx,by,br in [(15,22,4),(34,24,3),(20,34,3),(31,32,3),(24,16,3)]:
        fill_circle(c,bx,by,br,shade(B,0.88))
        outline_circle(c,bx,by,br,shade(B,0.55),1)
    for ex,ey in [(20,26),(30,22),(26,33)]:
        fill_circle(c,ex,ey,2,shade(B,0.42))
    fill_ellipse(c,18,19,5,3,(245,220,165,170))
    outline_ellipse(c,24,26,18,14,BLACK)
    save(c,"potato")

def draw_garlic():
    c=blank()
    B=(238,228,195,255)
    fill_ellipse(c,24,30,16,14,shade(B,0.88))
    fill_ellipse(c,24,30,14,12,B)
    for bx,bw,bh in [(18,5,8),(24,5,9),(30,5,8)]:
        fill_ellipse(c,bx,29,bw,bh,shade(B,1.06))
        line(c,bx,21,bx,37,shade(B,0.68),1)
    fill_ellipse(c,24,18,7,5,shade(B,0.84))
    fill_rect(c,22,10,25,17,(155,165,80,255))
    fill_circle(c,24,9,3,(165,180,70,255))
    fill_ellipse(c,18,23,4,3,(255,252,235,195))
    outline_ellipse(c,24,30,16,14,BLACK)
    line(c,17,18,30,18,BLACK)
    save(c,"garlic")

def draw_cabbage():
    c=blank()
    layers=[(20,18,(45,130,50,255)),(17,15,(80,175,65,255)),
            (13,11,(120,210,85,255)),(8,7,(165,235,115,255))]
    for rx,ry,col in layers:
        fill_ellipse(c,24,26,rx,ry,col)
    for ang in range(0,360,45):
        rad=math.radians(ang)
        x1=int(24+18*math.cos(rad)); y1=int(26+16*math.sin(rad))
        line(c,24,26,x1,y1,shade((45,130,50,255),0.68),1)
    fill_ellipse(c,17,18,5,3,(180,245,150,150))
    outline_ellipse(c,24,26,20,18,BLACK)
    save(c,"cabbage")

def draw_beef():
    c=blank()
    B=(165,60,50,255); FAT=(235,205,180,255)
    pts=[(12,18),(24,13),(36,15),(42,24),(40,34),(32,41),(16,42),(8,32),(9,22)]
    fill_poly(c,pts,B)
    fill_poly(c,[(12,18),(24,13),(36,15),(38,20),(22,18)],shade(B,1.32))
    fill_poly(c,[(36,15),(42,24),(40,34),(34,22)],shade(B,0.62))
    fill_poly(c,[(12,18),(24,13),(36,15),(34,19),(22,17),(12,21)],FAT)
    for y,x0,x1 in [(26,15,38),(32,14,36),(22,20,36)]:
        fill_rect(c,x0,y,x1,y+1,FAT)
    for i in range(len(pts)):
        x0,y0=pts[i]; x1,y1=pts[(i+1)%len(pts)]
        line(c,x0,y0,x1,y1,BLACK)
    save(c,"beef")

def draw_fish():
    c=blank()
    B=(110,165,215,255)
    fill_ellipse(c,26,26,19,13,B)
    fill_ellipse(c,23,24,16,10,shade(B,1.32))
    fill_ellipse(c,31,29,10, 7,shade(B,0.66))
    tail=[(42,16),(54,10),(54,42),(42,36)]
    fill_poly(c,tail,shade(B,0.84))
    for i in range(len(tail)):
        x0,y0=tail[i]; x1,y1=tail[(i+1)%len(tail)]
        line(c,x0,y0,x1,y1,BLACK)
    for row in range(3):
        for col in range(3):
            sx=16+col*7+(row%2)*3; sy=21+row*5
            fill_ellipse(c,sx,sy,3,2,shade(B,0.73))
    fill_circle(c,14,23,4,(250,250,250,255))
    fill_circle(c,14,23,2,(20,20,20,255))
    fill_circle(c,13,22,1,(255,255,255,200))
    outline_ellipse(c,26,26,19,13,BLACK)
    save(c,"fish")

def draw_egg():
    c=blank()
    fill_ellipse(c,24,28,16,18,(248,245,235,255))
    fill_ellipse(c,20,22,10, 8,(255,255,250,255))
    fill_ellipse(c,28,34, 9, 7,(215,210,195,255))
    fill_circle(c,24,26,10,(240,185,35,255))
    fill_circle(c,24,26, 9,(255,205,55,255))
    fill_circle(c,20,22, 3,(255,240,140,195))
    fill_circle(c,21,23, 1,(255,255,220,210))
    outline_ellipse(c,24,28,16,18,BLACK)
    outline_circle(c,24,26,10,shade((240,185,35,255),0.58))
    save(c,"egg")

def draw_noodle():
    c=blank()
    BOWL=(215,185,150,255); BROTH=(200,155,80,255); ND=(245,215,115,255)
    fill_poly(c,[(8,30),(40,30),(37,44),(11,44)],BOWL)
    fill_poly(c,[(8,30),(40,30),(39,35),(9,35)],shade(BOWL,0.78))
    fill_ellipse(c,24,30,16,6,BROTH)
    for i,base_y in enumerate([22,25,28]):
        col_=shade(ND,0.9+i*0.07)
        for x in range(10,38,5):
            dy=int(2*math.sin((x+i*4)*0.7))
            fill_rect(c,x,base_y+dy,x+3,base_y+dy+1,col_)
    line(c,5,8,26,34,(160,110,60,255),1)
    line(c,8,6,30,34,(175,120,65,255),1)
    for sx,bsy in [(16,14),(24,11),(32,14)]:
        for i,sy in enumerate(range(bsy,bsy+6,2)):
            a=int(140*(1-i/3))
            fill_circle(c,sx+int(math.sin(sy*0.9)*2),sy,2,(230,230,255,a))
    pts=[(8,30),(40,30),(37,44),(11,44)]
    for i in range(len(pts)):
        x0,y0=pts[i]; x1,y1=pts[(i+1)%len(pts)]
        line(c,x0,y0,x1,y1,BLACK)
    outline_ellipse(c,24,30,16,6,BLACK)
    save(c,"noodle")

def draw_rice():
    c=blank()
    BOWL=(215,190,160,255); RICE=(252,250,244,255)
    fill_poly(c,[(8,32),(40,32),(37,45),(11,45)],BOWL)
    fill_poly(c,[(8,32),(40,32),(39,37),(9,37)],shade(BOWL,0.76))
    fill_ellipse(c,24,28,17,11,shade(RICE,0.90))
    fill_ellipse(c,24,26,15, 9,RICE)
    for gx,gy in [(18,23),(23,21),(29,22),(15,26),(21,27),(28,26),(35,26),(20,30),(26,30),(32,30)]:
        fill_ellipse(c,gx,gy,3,2,shade(RICE,0.83))
    fill_ellipse(c,19,21,4,3,(255,255,255,175))
    pts=[(8,32),(40,32),(37,45),(11,45)]
    for i in range(len(pts)):
        x0,y0=pts[i]; x1,y1=pts[(i+1)%len(pts)]
        line(c,x0,y0,x1,y1,BLACK)
    outline_ellipse(c,24,28,17,11,BLACK)
    save(c,"rice")

def draw_cooked_dish():
    c=blank()
    PL=(228,222,210,255); FD=(205,140,55,255)
    fill_circle(c,24,28,18,shade(PL,0.87))
    fill_circle(c,24,28,16,PL)
    fill_circle(c,24,28,13,shade(PL,1.04))
    outline_circle(c,24,28,18,BLACK)
    outline_circle(c,24,28,13,shade(BLACK,3),1)
    fill_ellipse(c,24,26,12,8,shade(FD,0.73))
    fill_ellipse(c,24,24,11,7,FD)
    fill_ellipse(c,22,22, 7,5,shade(FD,1.36))
    for gx,gy in [(20,20),(27,19),(23,25),(18,24),(30,22)]:
        fill_circle(c,gx,gy,2,(75,170,60,255))
    for sx,bsy in [(18,10),(24,7),(30,10)]:
        for i,sy in enumerate(range(bsy,bsy+7,2)):
            a=int(150*(1-i/4))
            fill_circle(c,sx+int(math.sin(sy*1.1)*2),sy,2,(210,215,245,a))
    save(c,"cooked_dish")

def draw_burned_dish():
    c=blank()
    PL=(90,75,65,255)
    fill_circle(c,24,28,18,shade(PL,0.74))
    fill_circle(c,24,28,16,PL)
    fill_circle(c,24,28,13,shade(PL,0.58))
    outline_circle(c,24,28,18,BLACK)
    fill_ellipse(c,24,26,11,7,(25,18,12,255))
    fill_ellipse(c,22,24, 7,5,(38,28,18,255))
    for p in [[(22,22),(18,28)],[(26,21),(30,27)],[(20,26),(25,30)]]:
        line(c,p[0][0],p[0][1],p[1][0],p[1][1],(60,45,30,175),1)
    for sx,bsy in [(18,8),(24,5),(30,8)]:
        for i,sy in enumerate(range(bsy,bsy+9,3)):
            a=int(160*(1-i/3))
            fill_circle(c,sx+int(math.sin(sy*0.8)*3),sy,3,(85,80,80,a))
    save(c,"burned_dish")

# ── Chopped variants ──────────────────────────────────────────────────────────
def draw_chopped(name, base_col, inner_col):
    c=blank()
    skin=shade(base_col,0.63)
    offsets=[(-6,-4,13,10),(5,3,13,10)]
    for ox,oy,rx,ry in offsets:
        cx_,cy_=24+ox,26+oy
        fill_ellipse(c,cx_,cy_,rx,ry,skin)
        fill_ellipse(c,cx_,cy_,rx-2,ry-2,inner_col)
        fill_ellipse(c,cx_-rx//3,cy_-ry//3,max(1,rx//3),max(1,ry//3),shade(inner_col,1.28))
        if name in ("tomato","onion"):
            for sdx,sdy in [(-3,0),(0,-2),(3,0),(0,3)]:
                fill_circle(c,cx_+sdx,cy_+sdy,1,shade(inner_col,0.58))
        for ang in range(0,360,60):
            rad=math.radians(ang)
            x1=int(cx_+(rx-3)*math.cos(rad)); y1=int(cy_+(ry-3)*math.sin(rad))
            line(c,cx_,cy_,x1,y1,shade(inner_col,0.72),1)
        outline_ellipse(c,cx_,cy_,rx,ry,BLACK)
    line(c,6,6,42,42,(170,165,160,135),1)
    save(c,f"{name}_c")

# ── Run ───────────────────────────────────────────────────────────────────────
print("Generating pixel art ingredient assets...")

draw_tomato()
draw_onion()
draw_carrot()
draw_mushroom()
draw_potato()
draw_garlic()
draw_cabbage()
draw_beef()
draw_fish()
draw_egg()
draw_noodle()
draw_rice()

draw_chopped("tomato",   (210,45,45,255),  (240,160,150,255))
draw_chopped("onion",    (185,95,145,255), (235,185,210,255))
draw_chopped("carrot",   (235,120,30,255), (255,190,110,255))
draw_chopped("mushroom", (155,85,45,255),  (225,200,165,255))
draw_chopped("potato",   (185,140,75,255), (225,195,135,255))
draw_chopped("garlic",   (195,180,145,255),(248,242,220,255))
draw_chopped("cabbage",  (45,130,50,255),  (145,215,105,255))

draw_cooked_dish()
draw_burned_dish()

n=len(os.listdir("assets/ingredients"))
print(f"\nDone! {n} PNGs in assets/ingredients/")
