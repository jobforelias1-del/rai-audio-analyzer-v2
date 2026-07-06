"""Generate a clean waveform-style 1024x1024 icon for RAI Audio Analyzer.

Run from the project venv:
    python icon/make_icon.py
Produces: icon/rai.png
"""

import math
import os

from PIL import Image, ImageDraw, ImageFilter

SIZE = 1024
OUT_PATH = os.path.join(os.path.dirname(__file__), "rai.png")

# Color palette: deep navy background, bright cyan waveform.
BG_TOP = (18, 24, 46)
BG_BOTTOM = (32, 44, 86)
WAVE_MAIN = (96, 210, 255)
WAVE_GLOW = (96, 210, 255, 90)
CORNER_RADIUS = 224  # macOS Big Sur+ icon corner radius (~22% of edge)


def vertical_gradient(size, top, bottom):
    img = Image.new("RGB", (size, size), top)
    px = img.load()
    for y in range(size):
        t = y / (size - 1)
        r = int(top[0] + (bottom[0] - top[0]) * t)
        g = int(top[1] + (bottom[1] - top[1]) * t)
        b = int(top[2] + (bottom[2] - top[2]) * t)
        for x in range(size):
            px[x, y] = (r, g, b)
    return img


def rounded_mask(size, radius):
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, size, size), radius=radius, fill=255
    )
    return mask


def main():
    # 1) Rounded background with vertical gradient.
    bg = vertical_gradient(SIZE, BG_TOP, BG_BOTTOM)
    mask = rounded_mask(SIZE, CORNER_RADIUS)
    canvas = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    canvas.paste(bg, (0, 0), mask)

    # 2) Waveform bars — symmetric around the vertical center.
    n_bars = 21
    bar_w = 28
    gap = 22
    total_w = n_bars * bar_w + (n_bars - 1) * gap
    start_x = (SIZE - total_w) // 2
    cy = SIZE // 2

    # A pleasing height pattern (mix of two sines so it feels organic, not flat).
    heights = []
    for i in range(n_bars):
        t = i / (n_bars - 1)
        h = (
            0.55 * abs(math.sin(t * math.pi * 2.2))
            + 0.30 * abs(math.sin(t * math.pi * 5.1 + 0.7))
            + 0.10
        )
        heights.append(h)
    # Normalize so the tallest bar reaches a controlled fraction of the canvas.
    peak = max(heights)
    heights = [h / peak for h in heights]

    # 3) Glow layer — drawn first, blurred, slightly larger.
    glow = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    for i, h in enumerate(heights):
        half = int(h * SIZE * 0.34)
        x = start_x + i * (bar_w + gap)
        glow_draw.rounded_rectangle(
            (x - 6, cy - half - 6, x + bar_w + 6, cy + half + 6),
            radius=18,
            fill=WAVE_GLOW,
        )
    glow = glow.filter(ImageFilter.GaussianBlur(radius=22))

    # 4) Crisp waveform bars on top of the glow.
    bars = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bars_draw = ImageDraw.Draw(bars)
    for i, h in enumerate(heights):
        half = int(h * SIZE * 0.34)
        x = start_x + i * (bar_w + gap)
        bars_draw.rounded_rectangle(
            (x, cy - half, x + bar_w, cy + half),
            radius=14,
            fill=WAVE_MAIN,
        )

    # 5) Compose: background -> glow (clipped to rounded rect) -> bars (clipped).
    glow_clipped = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    glow_clipped.paste(glow, (0, 0), mask)
    bars_clipped = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bars_clipped.paste(bars, (0, 0), mask)

    canvas = Image.alpha_composite(canvas, glow_clipped)
    canvas = Image.alpha_composite(canvas, bars_clipped)

    canvas.save(OUT_PATH, "PNG")
    print(f"wrote {OUT_PATH} ({SIZE}x{SIZE})")


if __name__ == "__main__":
    main()
