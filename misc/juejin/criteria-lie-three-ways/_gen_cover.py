import os, random
from PIL import Image, ImageDraw, ImageFilter

random.seed(20261115)
W, H = 1920, 1080
img = Image.new('RGB', (W, H), (8, 10, 28))
px = img.load()
for y in range(H):
    for x in range(0, W, 4):
        t = (x / W * 0.6 + y / H * 0.4)
        r = int(18 + t * 60)
        g = int(20 + (1 - t) * 30)
        b = int(60 + t * 120)
        for dx in range(4):
            if x + dx < W:
                px[x + dx, y] = (r, g, b)
draw = ImageDraw.Draw(img, 'RGBA')
nodes = [(random.randint(120, W - 120), random.randint(120, H - 120)) for _ in range(14)]
for i in range(len(nodes)):
    for j in range(i + 1, len(nodes)):
        if random.random() < 0.35:
            draw.line([nodes[i], nodes[j]], fill=(120, 140, 255, 40), width=1)
for (x, y) in nodes:
    R = random.randint(10, 26)
    for rr in range(R, 0, -2):
        a = int(120 * (rr / R))
        draw.ellipse([x - rr, y - rr, x + rr, y + rr], outline=(150, 170, 255, max(8, a // 4)), width=1)
    draw.ellipse([x - 4, y - 4, x + 4, y + 4], fill=(200, 220, 255, 200))
glow = Image.new('RGBA', (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([int(W * 0.55), int(H * 0.30), int(W * 0.95), int(H * 0.85)], fill=(90, 60, 180, 30))
glow = glow.filter(ImageFilter.GaussianBlur(120))
img = Image.alpha_composite(img.convert('RGBA'), glow).convert('RGB')
out = os.path.join(os.path.dirname(__file__), 'cover.jpg')
img.save(out, 'JPEG', quality=88)
print('cover bytes:', os.path.getsize(out))
