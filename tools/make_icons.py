"""Generate the installable-app icons in docs/ (run once; the PNGs are committed).

Usage: python tools/make_icons.py
Needs Pillow and a font with the chess knight glyph (Segoe UI Symbol on Windows,
DejaVu Sans on Linux).
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

BG = (31, 42, 68)          # dark navy
FG = (255, 255, 255)
ACCENT = (76, 139, 245)    # theme primaryColor
KNIGHT = "\u265e"          # black chess knight (drawn filled, in white)

FONT_CANDIDATES = [
    "C:/Windows/Fonts/seguisym.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

OUT = Path(__file__).resolve().parent.parent / "docs"


def _font(px: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, px)
    raise SystemExit("No font with a chess knight glyph found")


def draw_icon(size: int, maskable: bool) -> Image.Image:
    scale = 4  # draw large, then downsample for smooth edges
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if maskable:
        # Full-bleed background; the launcher crops it to its own shape.
        d.rectangle([0, 0, s, s], fill=BG)
        glyph_frac = 0.52  # stays inside the 80% safe zone
    else:
        d.rounded_rectangle([0, 0, s - 1, s - 1], radius=int(s * 0.22), fill=BG)
        glyph_frac = 0.68
    # Accent bar under the knight.
    bar_w, bar_h = s * glyph_frac * 0.62, s * 0.035
    cx, cy = s / 2, s / 2
    font = _font(int(s * glyph_frac))
    box = d.textbbox((0, 0), KNIGHT, font=font)
    gw, gh = box[2] - box[0], box[3] - box[1]
    gx = cx - gw / 2 - box[0]
    gy = cy - gh / 2 - box[1] - bar_h * 1.2
    d.text((gx, gy), KNIGHT, font=font, fill=FG)
    bar_top = gy + box[3] + bar_h * 0.9
    d.rounded_rectangle(
        [cx - bar_w / 2, bar_top, cx + bar_w / 2, bar_top + bar_h],
        radius=int(bar_h / 2), fill=ACCENT,
    )
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    draw_icon(192, maskable=False).save(OUT / "icon-192.png")
    draw_icon(512, maskable=False).save(OUT / "icon-512.png")
    draw_icon(512, maskable=True).convert("RGB").save(OUT / "icon-maskable-512.png")
    draw_icon(180, maskable=True).convert("RGB").save(OUT / "apple-touch-icon.png")
    print("Icons written to docs/")


if __name__ == "__main__":
    main()
