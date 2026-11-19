#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""封面：断崖台阶（86->43）。16:9，纯几何，不嵌中文避免字体缺失乱码。"""
import os
from PIL import Image, ImageDraw, ImageFilter

W, H = 1920, 1080
OUT = os.path.join(os.path.dirname(__file__), "..", "static", "images",
                   "2026-11-20-job-pool-cliff-cover.png")

img = Image.new("RGB", (W, H), (8, 10, 28))
px = img.load()
for y in range(H):
    for x in range(0, W, 4):
        t = x / W * 0.55 + (1 - y / H) * 0.45
        r = int(16 + t * 46)
        g = int(18 + t * 34)
        b = int(56 + t * 130)
        for dx in range(4):
            if x + dx < W:
                px[x + dx, y] = (r, g, b)

glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([int(W * 0.08), int(H * 0.55), int(W * 0.55), int(H * 1.05)],
           fill=(70, 110, 255, 46))
glow = glow.filter(ImageFilter.GaussianBlur(130))
img = Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB")

draw = ImageDraw.Draw(img, "RGBA")

# 基准网格线
for i in range(1, 6):
    gy = int(H * 0.18 + i * H * 0.13)
    draw.line([(W * 0.10, gy), (W * 0.90, gy)], fill=(150, 170, 255, 22), width=2)

# 断崖台阶：86 / 84 / 71 / 43 四级 + 末端坠落
levels = [0.20, 0.24, 0.40, 0.72]
xs = [0.14, 0.36, 0.58, 0.80]
pts = []
for (xf, yf) in zip(xs, levels):
    pts.append((int(W * xf), int(H * yf)))

# 填充台阶下方
fill_pts = [(pts[0][0], int(H * 0.86))] + pts + [(pts[-1][0], int(H * 0.86))]
draw.polygon(fill_pts, fill=(80, 120, 255, 26))

# 台阶折线（水平段 + 垂直跌落）
for i in range(len(pts) - 1):
    x0, y0 = pts[i]
    x1, y1 = pts[i + 1]
    draw.line([(x0, y0), (x1, y0)], fill=(150, 185, 255, 230), width=7)
    draw.line([(x1, y0), (x1, y1)], fill=(255, 120, 150, 210), width=7)

# 节点光点 + 数字点阵（不用字体，用小圆点数量暗示 86/84/71/43）
for (x, y) in pts:
    for rr in range(26, 0, -3):
        a = int(120 * rr / 26)
        draw.ellipse([x - rr, y - rr, x + rr, y + rr],
                     outline=(170, 200, 255, max(6, a // 5)), width=2)
    draw.ellipse([x - 9, y - 9, x + 9, y + 9], fill=(220, 235, 255, 255))

# 末端坠落虚线到无读数
ex, ey = pts[-1]
draw.line([(ex, ey), (int(W * 0.90), int(H * 0.90))],
          fill=(255, 90, 120, 130), width=4)

img.save(OUT, "JPEG" if OUT.endswith(".jpg") else "PNG", quality=88)
print("cover bytes:", os.path.getsize(OUT))
print("cover size:", W, "x", H)
