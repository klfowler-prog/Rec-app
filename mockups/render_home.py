#!/usr/bin/env python3
"""Render the blend-centered home mockup to a flat PNG (mobile-safe)."""
from PIL import Image, ImageDraw, ImageFont

S = 2  # supersample for crispness
W, H = 450 * S, 1075 * S
CREAM = (246, 241, 231)
NAVY1, NAVY2 = (43, 58, 78), (24, 36, 52)
SAGE = (139, 158, 107); SAGE_D = (110, 131, 80)
CORAL = (232, 115, 74); CORAL_D = (197, 90, 52)
PURP = (107, 91, 138); AMBER = (197, 138, 58); SLATE = (58, 74, 94)
TXT = (43, 43, 41); MUT = (138, 138, 130); WHITE = (255, 255, 255)

FP = "/usr/share/fonts/truetype/liberation/"
def f(name, sz): return ImageFont.truetype(FP + name, sz * S)
REG  = lambda s: f("LiberationSans-Regular.ttf", s)
BOLD = lambda s: f("LiberationSans-Bold.ttf", s)
SER  = lambda s: f("LiberationSerif-Bold.ttf", s)

img = Image.new("RGB", (W, H), CREAM)
d = ImageDraw.Draw(img)

def rr(box, r, fill, outline=None, width=1):
    d.rounded_rectangle([c * S for c in box], radius=r * S, fill=fill,
                        outline=outline, width=width * S)

def text(xy, s, font, fill, anchor="la", spacing=4):
    d.text((xy[0] * S, xy[1] * S), s, font=font, fill=fill, anchor=anchor,
           spacing=spacing * S)

def tw(s, font): return d.textlength(s, font=font) / S

def wrap(s, font, maxw):
    words, lines, cur = s.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tw(t, font) <= maxw: cur = t
        else: lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines

def vgrad(box, c1, c2, r):
    x0, y0, x1, y1 = [c * S for c in box]
    h = y1 - y0
    g = Image.new("RGB", (x1 - x0, h))
    gd = ImageDraw.Draw(g)
    for i in range(h):
        t = i / max(h - 1, 1)
        gd.line([(0, i), (x1 - x0, i)],
                fill=tuple(int(c1[k] + (c2[k] - c1[k]) * t) for k in range(3)))
    mask = Image.new("L", (x1 - x0, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, x1 - x0 - 1, h - 1],
                                           radius=r * S, fill=255)
    img.paste(g, (x0, y0), mask)

# ── Header ───────────────────────────────────────────────────
text((20, 22), "NextUp", BOLD(19), TXT)
d.ellipse([(398) * S, 20 * S, (424) * S, 46 * S], fill=SAGE)
text((411, 33), "K", BOLD(13), WHITE, anchor="mm")
# search circle
d.ellipse([(364) * S, 20 * S, (390) * S, 46 * S], outline=(220, 215, 205),
          width=1 * S)
d.ellipse([(372) * S, 28 * S, (380) * S, 36 * S], outline=MUT, width=1 * S)
d.line([(379) * S, 35 * S, (383) * S, 39 * S], fill=MUT, width=1 * S)

# ── Greeting (serif) ─────────────────────────────────────────
text((20, 60), "Friday night, Kelly.", SER(22), NAVY1)
text((20, 86), "What two things are we mixing?", SER(22), (90, 104, 120))

# ── BLEND HERO ───────────────────────────────────────────────
hx0, hy0, hx1, hy1 = 16, 124, 434, 432
vgrad((hx0, hy0, hx1, hy1), NAVY1, NAVY2, 24)
# soft glows — clipped to the hero card so they don't bleed out
glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
gd = ImageDraw.Draw(glow)
gd.ellipse([330 * S, 120 * S, 460 * S, 250 * S], fill=(139, 158, 107, 70))
gd.ellipse([40 * S, 300 * S, 170 * S, 430 * S], fill=(232, 115, 74, 55))
clip = Image.new("L", (W, H), 0)
ImageDraw.Draw(clip).rounded_rectangle(
    [hx0 * S, hy0 * S, hx1 * S, hy1 * S], radius=24 * S, fill=255)
glow.putalpha(Image.composite(glow.getchannel("A"),
                              Image.new("L", (W, H), 0), clip))
img.paste(Image.alpha_composite(img.convert("RGBA"), glow).convert("RGB"),
          (0, 0))
d = ImageDraw.Draw(img)

# Rung selector pill
rr((30, 140, 420, 168), 14, (255, 255, 255, 30) and (60, 74, 92))
rr((32, 142, 162, 166), 12, WHITE)
text((97, 154), "Two titles", BOLD(11), NAVY1, anchor="mm")
text((227, 154), "You + a mood", BOLD(11), (200, 206, 214), anchor="mm")
text((357, 154), "You + someone", BOLD(11), (200, 206, 214), anchor="mm")

# Input A
rr((30, 178, 420, 212), 12, (60, 74, 92))
text((44, 195), "A", BOLD(10), (150, 160, 172), anchor="lm")
text((62, 195), "Severance", REG(14), WHITE, anchor="lm")
# x badge
d.ellipse([209 * S, 210 * S, 241 * S, 242 * S], fill=CORAL,
          outline=NAVY2, width=4 * S)
text((225, 226), "×", BOLD(16), WHITE, anchor="mm")
# Input B
rr((30, 240, 420, 274), 12, (60, 74, 92))
text((44, 257), "B", BOLD(10), (150, 160, 172), anchor="lm")
text((62, 257), "Fleabag", REG(14), WHITE, anchor="lm")

# Blend button
rr((30, 286, 420, 322), 12, CORAL)
text((215, 304), "Blend them  →", BOLD(15), WHITE, anchor="mm")

# tap-to-mix
text((30, 338), "OR TAP TO MIX", BOLD(9), (150, 160, 172))
def chip(x, y, label, w):
    rr((x, y, x + w, y + 26), 13, (60, 74, 92))
    text((x + w / 2, y + 13), label, REG(11), (225, 228, 233), anchor="mm")
chip(30, 354, "The Bear × Chef's Table", 158)
chip(196, 354, "You × rainy Sunday", 130)
# "You × Maya" chip with a leading avatar badge (badge sits inside the pill)
rr((30, 388, 142, 414), 13, (60, 74, 92))
d.ellipse([38 * S, 394 * S, 54 * S, 410 * S], fill=CORAL)
text((46, 401), "M", BOLD(9), WHITE, anchor="mm")
text((86, 401), "You × Maya", REG(11), (225, 228, 233), anchor="mm")

# ── RESULT ───────────────────────────────────────────────────
text((22, 452), "YOUR LAST BLEND", BOLD(10), SAGE_D)
text((428, 452), "Severance × Fleabag", REG(11), MUT, anchor="ra")
rr((16, 472, 434, 612), 16, WHITE, outline=(232, 228, 218), width=1)
# poster
vgrad((16, 472, 128, 580), PURP, (82, 68, 112), 0)
rr((16, 472, 128, 580), 0, None)  # noop keep
text((72, 520), "The", SER(17), (255, 255, 255), anchor="mm")
text((72, 540), "Leftovers", SER(17), (255, 255, 255), anchor="mm")
# right
text((142, 484), "LIVING IN THE OVERLAP", BOLD(9), MUT)
text((142, 498), "The Leftovers", BOLD(16), TXT)
text((142, 520), "TV · 2014", REG(11), MUT)
para = ("Severance's eerie institutional dread meets Fleabag's raw, funny "
        "grief — people performing normalcy over a wound. Dead-center of both.")
yy = 534
for ln in wrap(para, REG(11), 280):
    text((142, yy), ln, REG(11), (70, 75, 82)); yy += 15
# buttons
rr((142, 582, 232, 604), 8, SAGE)
text((187, 593), "Add to queue", BOLD(10), WHITE, anchor="mm")
rr((240, 582, 300, 604), 8, (239, 234, 224))
text((270, 593), "Share", BOLD(10), TXT, anchor="mm")

# ── STILL INTO ───────────────────────────────────────────────
text((22, 636), "STILL INTO", BOLD(10), CORAL)
posters = [("Andor", SLATE), ("Tomorrow×3", AMBER), ("The Bear", PURP)]
px = 20
for name, col in posters:
    vgrad((px, 656, px + 72, 760), col, tuple(int(c * .8) for c in col), 10)
    text((px + 36, 708), name, BOLD(11), WHITE, anchor="mm")
    px += 84
# add tile
d.rounded_rectangle([px * S, 656 * S, (px + 72) * S, 760 * S], radius=10 * S,
                    outline=(210, 205, 195), width=2 * S)
text((px + 36, 708), "+ Add", BOLD(11), MUT, anchor="mm")

# ── TASTE STRENGTH ───────────────────────────────────────────
rr((16, 784, 434, 848), 16, WHITE, outline=(232, 228, 218), width=1)
bars = [(34, 18), (44, 24), (54, 30), (64, 36), (74, 42)]
bx = 32
for i, (yt, hh) in enumerate([(820, 12), (816, 18), (812, 24), (808, 30),
                              (804, 36)]):
    col = SAGE if i < 3 else (200, 210, 185)
    rr((bx, yt, bx + 5, 820), 3, col); bx += 9
text((86, 800), "Your taste is getting sharp", BOLD(12), TXT)
text((86, 818), "Rate 3 more and your blends get noticeably better.",
     REG(11), MUT)
text((420, 816), "Rate →", BOLD(11), SAGE_D, anchor="ra")

text((225, 868), "mockup · not wired", REG(9), (190, 185, 175), anchor="mm")

img = img.resize((W // S, H // S), Image.LANCZOS)
img.save("/home/user/Rec-app/mockups/home_blend.png", "PNG")
print("saved")
