#!/usr/bin/env python3
"""
Generate InfoCord app icons (Gate C2).

Design: Syne Bold "IC" in white on #0e0f11; minimalist eye (ring + pupil) atop the I.
Outputs 1024×1024 master, Android adaptive layers, web favicons, and mobile asset.

  python images/icon_generation.py
"""
from __future__ import annotations

import ssl
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FONTS_DIR = ROOT / "fonts"
FONT_PATH = FONTS_DIR / "Syne-wght.ttf"
FONT_URL = (
    "https://raw.githubusercontent.com/google/fonts/refs/heads/main/ofl/syne/Syne%5Bwght%5D.ttf"
)

BG = (14, 15, 17, 255)  # #0e0f11 — matches web/mobile theme
WHITE = (255, 255, 255, 255)
MASTER_SIZE = 1024


def ensure_font() -> Path:
    FONTS_DIR.mkdir(parents=True, exist_ok=True)
    if FONT_PATH.exists() and FONT_PATH.stat().st_size > 10_000:
        return FONT_PATH
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    with urllib.request.urlopen(FONT_URL, context=ctx) as resp:
        FONT_PATH.write_bytes(resp.read())
    if FONT_PATH.stat().st_size < 10_000:
        raise RuntimeError(f"Font download failed ({FONT_PATH.stat().st_size} bytes)")
    return FONT_PATH


def _measure(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _draw_logo(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float = 1.0) -> None:
    font_path = ensure_font()
    font_size = int(420 * scale)
    font = ImageFont.truetype(str(font_path), font_size)

    i_w, i_h = _measure(draw, "I", font)
    gap = int(18 * scale)
    c_w, c_h = _measure(draw, "C", font)
    total_w = i_w + gap + c_w
    top = cy - max(i_h, c_h) // 2

    i_x = cx - total_w // 2
    c_x = i_x + i_w + gap
    draw.text((i_x, top), "I", fill=WHITE, font=font)
    draw.text((c_x, top), "C", fill=WHITE, font=font)

    # Eye atop I — centered over the I stem
    eye_cx = i_x + i_w // 2
    eye_cy = top - int(52 * scale)
    outer_r = int(34 * scale)
    inner_r = int(14 * scale)
    ring_w = max(4, int(7 * scale))
    draw.ellipse(
        (eye_cx - outer_r, eye_cy - outer_r, eye_cx + outer_r, eye_cy + outer_r),
        outline=WHITE,
        width=ring_w,
    )
    draw.ellipse(
        (eye_cx - inner_r, eye_cy - inner_r, eye_cx + inner_r, eye_cy + inner_r),
        fill=WHITE,
    )


def render_master(size: int = MASTER_SIZE, transparent: bool = False) -> Image.Image:
    mode = "RGBA"
    bg = (0, 0, 0, 0) if transparent else BG
    img = Image.new(mode, (size, size), bg)
    draw = ImageDraw.Draw(img)
    _draw_logo(draw, size // 2, size // 2 + int(size * 0.04), scale=size / MASTER_SIZE)
    return img


def save_png(img: Image.Image, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path, "PNG", optimize=True)
    print(f"  wrote {path.relative_to(ROOT)}")


def export_sizes(master: Image.Image) -> None:
    targets: list[tuple[Path, int]] = [
        (ROOT / "images" / "app_icon_1024.png", 1024),
        (ROOT / "mobile" / "assets" / "icons" / "app_icon.png", 1024),
        (ROOT / "mobile" / "assets" / "icons" / "app_icon_foreground.png", 1024),
        (ROOT / "static" / "icons" / "icon-512.png", 512),
        (ROOT / "static" / "icons" / "icon-192.png", 192),
        (ROOT / "static" / "icons" / "apple-touch-icon.png", 180),
        (ROOT / "static" / "icons" / "favicon-32.png", 32),
        (ROOT / "static" / "icons" / "favicon-16.png", 16),
    ]
    for path, dim in targets:
        resized = master.resize((dim, dim), Image.Resampling.LANCZOS)
        save_png(resized, path)

    # Android adaptive background — solid brand color
    bg_img = Image.new("RGBA", (1024, 1024), BG)
    save_png(bg_img, ROOT / "mobile" / "assets" / "icons" / "app_icon_background.png")

    # Splash reference (same as master, for flutter_native_splash)
    save_png(master, ROOT / "mobile" / "assets" / "icons" / "splash_logo.png")

    # ICO for legacy browsers
    ico_path = ROOT / "static" / "icons" / "favicon.ico"
    master.resize((32, 32), Image.Resampling.LANCZOS).save(
        ico_path, format="ICO", sizes=[(16, 16), (32, 32)]
    )
    print(f"  wrote {ico_path.relative_to(ROOT)}")


def main() -> None:
    print("InfoCord icon generation (Gate C2)")
    fg = render_master(MASTER_SIZE, transparent=True)
    save_png(fg, ROOT / "mobile" / "assets" / "icons" / "app_icon_foreground.png")

    master = render_master(MASTER_SIZE, transparent=False)
    export_sizes(master)
    print("Done.")


if __name__ == "__main__":
    main()
