"""Generate a shareable Taste DNA image card using Pillow.

Produces a 1080x1350 PNG (Instagram portrait ratio) designed to
look great when screenshotted or shared to social media. Bold
headline, readable summary, minimal clutter, poster strip.
"""

import io
import logging
import textwrap
from pathlib import Path

import httpx
from PIL import Image, ImageDraw, ImageFont

log = logging.getLogger(__name__)

W, H = 1080, 1350
SAGE = (139, 158, 107)
CORAL = (232, 115, 74)


def _get_font(size: int, bold: bool = False):
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ]
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default(size)


def _get_italic_font(size: int):
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


def _fetch_poster(url: str, size: tuple[int, int] = (140, 200)) -> Image.Image | None:
    """Download a poster image and resize it. Returns None on failure."""
    try:
        resp = httpx.get(url, timeout=5, follow_redirects=True)
        if resp.status_code == 200 and len(resp.content) > 1000:
            poster = Image.open(io.BytesIO(resp.content)).convert("RGBA")
            poster = poster.resize(size, Image.LANCZOS)
            return poster
    except Exception:
        pass
    return None


def generate_share_card(
    user_name: str,
    summary: str,
    themes: list[str],
    signature_items: list[str],
    poster_urls: list[str] | None = None,
) -> bytes:
    """Generate a shareable PNG card and return the bytes."""
    img = Image.new("RGBA", (W, H))
    draw = ImageDraw.Draw(img)

    # Rich gradient background — navy to deep navy with warm tint
    for y in range(H):
        ratio = y / H
        r = int(38 * (1 - ratio) + 25 * ratio)
        g = int(52 * (1 - ratio) + 35 * ratio)
        b = int(72 * (1 - ratio) + 52 * ratio)
        draw.line([(0, y), (W, y)], fill=(r, g, b, 255))

    # Decorative gradient orbs
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    for i in range(250):
        a = int(50 * (1 - i / 250))
        od.ellipse([W - 250 + i // 2, -120 + i // 2, W + 250 - i // 2, 380 - i // 2],
                    fill=(SAGE[0], SAGE[1], SAGE[2], a))
    for i in range(200):
        a = int(35 * (1 - i / 200))
        od.ellipse([-50 + i // 2, H - 400 + i // 2, 400 - i // 2, H + 50 - i // 2],
                    fill=(CORAL[0], CORAL[1], CORAL[2], a))
    img = Image.alpha_composite(img, overlay)
    draw = ImageDraw.Draw(img)

    # Fonts
    font_brand = _get_font(32, bold=True)
    font_label = _get_font(18, bold=True)
    font_name = _get_font(52, bold=True)
    font_summary = _get_italic_font(30)
    font_theme = _get_font(28)
    font_footer = _get_font(20)

    y = 70

    # Brand
    draw.text((80, y), "NextUp", fill=SAGE, font=font_brand)
    y += 60

    # Big headline — user's first name
    first_name = user_name.split()[0] if user_name else "Your"
    draw.text((80, y), f"{first_name}'s", fill=(255, 255, 255, 120), font=font_name)
    y += 65
    draw.text((80, y), "Taste DNA", fill=(255, 255, 255, 255), font=font_name)
    y += 90

    # Accent line
    draw.rounded_rectangle([80, y, 180, y + 4], radius=2, fill=SAGE)
    y += 35

    # Summary — truncate to complete sentences that fit the card
    if summary:
        # Split into sentences and take as many as fit in ~250 chars
        import re
        sentences = re.split(r'(?<=[.!?])\s+', summary.strip())
        truncated = ""
        for s in sentences:
            if len(truncated) + len(s) + 1 > 260:
                break
            truncated = (truncated + " " + s).strip()
        if not truncated and sentences:
            truncated = sentences[0][:260]

        wrapped = textwrap.wrap(truncated, width=40)
        for line in wrapped[:6]:
            draw.text((80, y), line, fill=(255, 255, 255, 220), font=font_summary)
            y += 42
    y += 35

    # Themes — clean, minimal
    if themes:
        draw.text((80, y), "SIGNATURE THEMES", fill=(255, 255, 255, 80), font=font_label)
        y += 38
        for theme in themes[:3]:
            draw.text((80, y), f"—  {theme}", fill=(255, 255, 255, 190), font=font_theme)
            y += 40
        y += 15

    # Poster strip at the bottom — fetched from URLs
    if poster_urls:
        poster_y = H - 280
        poster_w, poster_h = 140, 200
        posters_fetched = []
        for url in poster_urls[:6]:
            p = _fetch_poster(url, (poster_w, poster_h))
            if p:
                posters_fetched.append(p)

        if posters_fetched:
            # Dark overlay strip behind posters
            strip_overlay = Image.new("RGBA", (W, poster_h + 40), (0, 0, 0, 80))
            img.paste(strip_overlay, (0, poster_y - 20), strip_overlay)

            # Center the posters
            total_w = len(posters_fetched) * (poster_w + 12) - 12
            start_x = (W - total_w) // 2
            for i, poster in enumerate(posters_fetched):
                x = start_x + i * (poster_w + 12)
                # Rounded corners
                mask = Image.new("L", (poster_w, poster_h), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle([0, 0, poster_w, poster_h], radius=10, fill=255)
                img.paste(poster, (x, poster_y), mask)

            draw = ImageDraw.Draw(img)

    # Footer
    footer_y = H - 60
    draw.text((80, footer_y), "Find yours at nextup.app", fill=(255, 255, 255, 80), font=font_footer)

    # Output
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="PNG", quality=95)
    buf.seek(0)
    return buf.getvalue()
