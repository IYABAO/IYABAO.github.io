import os, random
from PIL import Image, ImageDraw, ImageFilter

random.seed(20261115)
W, H = 1920, 1080
img = Image.new('RGB', (W, H), (8, 10, 28))
px = img.load()
for y in range(H):
    for x in range(0, W, 4):
        t = (x / W * 0.6 + y / H * 0.4)
        r = int(14 + t * 52)
        g = int(18 + (1 - t) * 30)
        b = int(56 + t * 128)
        for dx in range(4):
            if x + dx < W:
                px[x + dx, y] = (r, g, b)
draw = ImageDraw.Draw(img, 'RGBA')

# 三条「进度条」：左段实心 = 实体工作成立；红色断口 = 交付不成立；右段虚线 = 没接上的交付
bar_x0, bar_x1 = 200, 1720
rows = [(300, 0.62), (530, 0.78), (760, 0.55)]
for (cy, frac) in rows:
    bar_h = 88
    y0, y1 = cy - bar_h // 2, cy + bar_h // 2
    # 底槽
    draw.rounded_rectangle([bar_x0, y0, bar_x1, y1], radius=18, fill=(30, 40, 78, 200), outline=(70, 90, 160, 160), width=2)
    cut = int(bar_x0 + (bar_x1 - bar_x0) * frac)
    # 实心已完成段
    draw.rounded_rectangle([bar_x0 + 6, y0 + 6, cut - 10, y1 - 6], radius=12, fill=(70, 130, 235, 235))
    draw.rounded_rectangle([bar_x0 + 6, y0 + 6, cut - 10, y0 + 24], radius=10, fill=(140, 185, 255, 90))
    # 右段虚线（未接上的交付）
    x = cut + 34
    while x < bar_x1 - 20:
        draw.rounded_rectangle([x, y0 + 22, min(x + 46, bar_x1 - 16), y1 - 22], radius=6, fill=(110, 130, 200, 70))
        x += 78
    # 红色断口竖线 + 叉
    draw.line([(cut, y0 - 22), (cut, y1 + 22)], fill=(240, 80, 90, 235), width=7)
    draw.line([(cut - 14, cy - 14), (cut + 14, cy + 14)], fill=(255, 150, 150, 220), width=4)
    draw.line([(cut - 14, cy + 14), (cut + 14, cy - 14)], fill=(255, 150, 150, 220), width=4)

# 背景装饰节点
nodes = [(random.randint(90, W - 90), random.randint(70, H - 70)) for _ in range(12)]
for i in range(len(nodes)):
    for j in range(i + 1, len(nodes)):
        if random.random() < 0.22:
            draw.line([nodes[i], nodes[j]], fill=(110, 135, 230, 26), width=1)
for (x, y) in nodes:
    draw.ellipse([x - 3, y - 3, x + 3, y + 3], fill=(170, 195, 255, 120))

glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([int(W * 0.60), int(H * 0.05), int(W * 1.0), int(H * 0.7)], fill=(80, 60, 180, 26))
glow = glow.filter(ImageFilter.GaussianBlur(130))
img = Image.alpha_composite(img.convert('RGBA'), glow).convert('RGB')
out = os.path.join(os.path.dirname(__file__), 'cover.jpg')
img.save(out, 'JPEG', quality=88)
print('cover size:', img.size, 'bytes:', os.path.getsize(out))
