"""Generate a shareable Taste DNA image card using Pillow.

Produces a 1080x1350 PNG (Instagram portrait ratio) with:
- Dark gradient background
- User name + "Taste DNA" header
- The "who you are" summary paragraph
- Top 3 signature themes
- Signature items as pills
- NextUp branding at the bottom
"""

import io
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1080, 1350
BG_TOP = (43, 58, 78)       # navy
BG_BOT = (30, 42, 58)       # darker navy
SAGE = (139, 158, 107)
CORAL = (232, 115, 74)
WHITE = (255, 255, 255)
WHITE_DIM = (255, 255, 255, 180)
WHITE_FAINT = (255, 255, 255, 100)


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Try system fonts, fall back to Pillow default."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size)


def _get_italic_font(size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return _get_font(size)


def generate_share_card(
    user_name: str,
    summary: str,
    themes: list[str],
    signature_items: list[str],
) -> bytes:
    """Generate a shareable PNG card and return the bytes."""
    img = Image.new("RGBA", (W, H), BG_TOP)
    draw = ImageDraw.Draw(img)

    # Gradient background
    for y in range(H):
        ratio = y / H
        r = int(BG_TOP[0] * (1 - ratio) + BG_BOT[0] * ratio)
        g = int(BG_TOP[1] * (1 - ratio) + BG_BOT[1] * ratio)
        b = int(BG_TOP[2] * (1 - ratio) + BG_BOT[2] * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # Decorative circles
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    # Sage orb top-right
    for i in range(200):
        alpha = int(40 * (1 - i / 200))
        od.ellipse([W - 200 + i // 2, -100 + i // 2, W + 200 - i // 2, 300 - i // 2],
                    fill=(SAGE[0], SAGE[1], SAGE[2], alpha))
    # Coral orb bottom-left
    for i in range(150):
        alpha = int(30 * (1 - i / 150))
        od.ellipse([50 + i // 2, H - 350 + i // 2, 350 - i // 2, H - 50 - i // 2],
                    fill=(CORAL[0], CORAL[1], CORAL[2], alpha))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_tiny = _get_font(20)
    font_small = _get_font(24)
    font_label = _get_font(22, bold=True)
    font_name = _get_font(28, bold=True)
    font_header = _get_font(16, bold=True)
    font_summary = _get_italic_font(32)
    font_theme = _get_font(26)
    font_pill = _get_font(20)
    font_brand = _get_font(36, bold=True)

    y = 80

    # NextUp branding
    draw.text((80, y), "NextUp", fill=SAGE, font=font_brand)
    draw.text((80 + draw.textlength("NextUp  ", font=font_brand), y + 10),
              "Taste DNA", fill=WHITE_FAINT, font=font_small)
    y += 80

    # User name
    draw.text((80, y), f"{user_name}'s Taste DNA", fill=WHITE_DIM, font=font_name)
    y += 60

    # Divider
    draw.line([(80, y), (W - 80, y)], fill=(255, 255, 255, 40), width=1)
    y += 40

    # Summary — wrapped
    if summary:
        wrapped = textwrap.wrap(summary, width=42)
        for line in wrapped[:8]:
            draw.text((80, y), line, fill=(255, 255, 255, 230), font=font_summary)
            y += 44
    y += 30

    # Divider
    draw.line([(80, y), (W - 80, y)], fill=(255, 255, 255, 40), width=1)
    y += 35

    # Themes
    if themes:
        draw.text((80, y), "SIGNATURE THEMES", fill=WHITE_FAINT, font=font_header)
        y += 40
        for theme in themes[:3]:
            # Sage dot
            draw.ellipse([80, y + 8, 92, y + 20], fill=SAGE)
            draw.text((105, y), theme, fill=(255, 255, 255, 210), font=font_theme)
            y += 42
        y += 20

    # Signature items as pills
    if signature_items:
        draw.text((80, y), "DEFINING ITEMS", fill=WHITE_FAINT, font=font_header)
        y += 40
        x = 80
        for item in signature_items[:5]:
            tw = draw.textlength(item, font=font_pill)
            pill_w = tw + 30
            if x + pill_w > W - 80:
                x = 80
                y += 42
            # Pill background
            draw.rounded_rectangle([x, y, x + pill_w, y + 34], radius=17,
                                    fill=(255, 255, 255, 25))
            draw.text((x + 15, y + 5), item, fill=(255, 255, 255, 180), font=font_pill)
            x += pill_w + 10
        y += 60

    # Footer
    y = H - 80
    draw.line([(80, y - 20), (W - 80, y - 20)], fill=(255, 255, 255, 30), width=1)
    draw.text((80, y), "Find your next thing", fill=WHITE_FAINT, font=font_tiny)
    draw.text((W - 80 - draw.textlength("nextup.app", font=font_tiny), y),
              "nextup.app", fill=WHITE_FAINT, font=font_tiny)

    # Convert to PNG bytes
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf.getvalue()
