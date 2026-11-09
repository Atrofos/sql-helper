"""Draw the SQL Helper app icon (developer tool, not needed to run the app).

Writes sql_helper/assets/icon.png (used for the Dock icon at runtime) and
sql_helper/assets/icon.icns (used by SQL Helper.app in Finder and the Dock).
Requires Pillow, plus macOS's built-in `sips` and `iconutil` for the .icns:

    python3 tools/make_icon.py

The generated files are committed, so normal users never need to run this.
"""

import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "sql_helper" / "assets"
S = 2048                      # draw at 2x, then downsample for smooth edges
TOP, BOTTOM = (37, 99, 235), (13, 148, 136)   # blue -> teal
WHITE, INK, GREEN = (255, 255, 255), (30, 64, 175), (34, 197, 94)


def lerp(a, b, t):
    return tuple(round(x + (y - x) * t) for x, y in zip(a, b))


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square background on Apple's icon grid (824/1024 of the canvas).
    inset, radius = int(S * 100 / 1024), int(S * 185 / 1024)
    gradient = Image.new("RGBA", (S, S))
    gd = ImageDraw.Draw(gradient)
    for y in range(S):
        gd.line([(0, y), (S, y)], fill=lerp(TOP, BOTTOM, y / S))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([inset, inset, S - inset, S - inset], radius, fill=255)
    img.paste(gradient, (0, 0), mask)

    d = ImageDraw.Draw(img)
    # Database cylinder.
    cx, w, eh = S // 2 - int(S * 0.04), int(S * 0.40), int(S * 0.11)
    top, bottom = int(S * 0.27), int(S * 0.66)
    left, right = cx - w // 2, cx + w // 2
    d.rectangle([left, top + eh // 2, right, bottom], fill=WHITE)
    d.ellipse([left, bottom - eh // 2, right, bottom + eh // 2], fill=WHITE)
    band = int(S * 0.012)
    band_ys = (top + int((bottom - top) * 0.60), top + int((bottom - top) * 0.84))
    for y in band_ys:
        d.arc([left, y - eh // 2, right, y + eh // 2], 0, 180, fill=lerp(TOP, BOTTOM, 0.3), width=band)
    d.ellipse([left, top, right, top + eh], fill=(219, 234, 254))
    d.ellipse([left, top, right, top + eh], outline=WHITE, width=band)

    # "SQL" on the cylinder.
    font = ImageFont.truetype("/System/Library/Fonts/Menlo.ttc", int(S * 0.095), index=1)
    text_y = (top + eh + band_ys[0]) // 2   # centred between the lid and the first band
    d.text((cx, text_y), "SQL", font=font, fill=INK, anchor="mm")

    # Green "correct" badge, bottom right.
    bx, by, br = int(S * 0.68), int(S * 0.68), int(S * 0.135)
    ring = int(S * 0.022)
    d.ellipse([bx - br - ring, by - br - ring, bx + br + ring, by + br + ring], fill=WHITE)
    d.ellipse([bx - br, by - br, bx + br, by + br], fill=GREEN)
    d.line([(bx - br * 0.48, by + br * 0.02), (bx - br * 0.12, by + br * 0.38),
            (bx + br * 0.52, by - br * 0.36)], fill=WHITE, width=int(S * 0.034), joint="curve")
    return img.resize((1024, 1024), Image.LANCZOS)


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    icon = draw()
    icon.save(ASSETS / "icon_1024.png")
    icon.resize((512, 512), Image.LANCZOS).save(ASSETS / "icon.png")

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            icon.resize((size, size), Image.LANCZOS).save(iconset / f"icon_{size}x{size}.png")
            icon.resize((size * 2, size * 2), Image.LANCZOS).save(iconset / f"icon_{size}x{size}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(ASSETS / "icon.icns")],
                       check=True)
    (ASSETS / "icon_1024.png").unlink()
    print("Wrote", ASSETS / "icon.png", "and", ASSETS / "icon.icns")


if __name__ == "__main__":
    if shutil.which("iconutil") is None:
        raise SystemExit("iconutil not found: run this on macOS.")
    main()
