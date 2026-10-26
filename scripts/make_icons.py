"""Rahbar ilovasi belgisi (iPhone bosh ekrani uchun): lojuvard fon, derazalari yoniq uchta bino."""
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parent.parent / "rahbar" / "static"
S = 1024
img = Image.new("RGB", (S, S))
px = img.load()
top, bot = (58, 99, 201), (23, 50, 122)
for y in range(S):
    k = y / (S - 1)
    c = tuple(int(top[i] + (bot[i] - top[i]) * k) for i in range(3))
    for x in range(S):
        px[x, y] = c
d = ImageDraw.Draw(img)
# yorug'lik doirasi
glow = Image.new("L", (S, S), 0)
ImageDraw.Draw(glow).ellipse((560, 120, 900, 460), fill=90)
glow = glow.filter(ImageFilter.GaussianBlur(60))
img.paste((242, 181, 68), (0, 0), glow)
d = ImageDraw.Draw(img)
rnd = random.Random(3)
ground = 830
blocks = [(170, 380, 420), (395, 250, 650), (625, 430, 860)]  # (x0, topY, x1)
for x0, ty, x1 in blocks:
    d.rounded_rectangle((x0, ty, x1, ground), radius=18, fill=(232, 238, 251))
    cols = 3
    w = (x1 - x0 - 40) / cols
    y = ty + 34
    while y + 46 < ground - 20:
        for c in range(cols):
            wx = x0 + 20 + c * w + 10
            lit = rnd.random() < 0.55
            d.rounded_rectangle((wx, y, wx + w - 20, y + 42), radius=6,
                                fill=(242, 181, 68) if lit else (157, 172, 204))
        y += 64
d.rounded_rectangle((120, ground, 904, ground + 16), radius=8, fill=(242, 181, 68))
OUT.mkdir(parents=True, exist_ok=True)
for size, name in [(512, "icon-512.png"), (192, "icon-192.png"), (180, "apple-touch-icon.png")]:
    img.resize((size, size), Image.LANCZOS).save(OUT / name, optimize=True)
print("ok", OUT)
