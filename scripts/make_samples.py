#!/usr/bin/env python3
"""Generate the demo's sample images. Regenerable, so they need not be sacred."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

OUT = Path("samples")
FONTS = (
    "/System/Library/Fonts/Supplemental/Songti.ttc",   # macOS
    "/usr/share/fonts/truetype/arphic/uming.ttc",      # Debian/RPi
    "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONTS:
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    raise SystemExit(f"no CJK font found; tried {FONTS}")


def note(name: str, lines, bg=(252, 246, 214), size=(900, 620)) -> None:
    img = Image.new("RGB", size, bg)
    draw = ImageDraw.Draw(img)
    y = 60
    for text, pt in lines:
        draw.text((60, y), text, font=_font(pt), fill=(38, 38, 44))
        y += int(pt * 1.75)
    OUT.mkdir(exist_ok=True)
    img.save(OUT / name, quality=95)
    print(f"  wrote samples/{name}")


def main() -> None:
    note("note.jpg", [
        ("感冒灵颗粒", 60),
        ("每次 1 袋，一日 3 次", 40),
        ("饭后温水冲服", 40),
        ("儿童酌减 / 孕妇慎用", 34),
        ("批号 20260518", 30),
    ])
    note("todo.jpg", [
        ("明天要做", 54),
        ("1. 交房租 3200", 38),
        ("2. 给妈妈回电话", 38),
        ("3. 取快递 丰巢 8823", 38),
    ], bg=(232, 240, 247))

    # A presence pair: one still frame, one with a large change. Also doubles as
    # the "no text at all" image that makes the local OCR engine decline.
    OUT.mkdir(exist_ok=True)
    base = np.full((480, 640, 3), 120, np.uint8)
    cv2.imwrite(str(OUT / "presence_a.jpg"), base)
    moved = base.copy()
    cv2.rectangle(moved, (120, 80), (520, 420), (240, 240, 240), -1)
    cv2.imwrite(str(OUT / "presence_b.jpg"), moved)
    print("  wrote samples/presence_a.jpg, samples/presence_b.jpg")


if __name__ == "__main__":
    main()
