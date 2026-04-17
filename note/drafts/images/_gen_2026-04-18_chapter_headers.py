"""One-off: chapter header PNGs for note draft 2026-04-18. Run: py -3 _gen_2026-04-18_chapter_headers.py"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 1200, 630
OUT = Path(__file__).resolve().parent

# (filename_stem, title, accent RGB, secondary RGB)
CHAPTERS: list[tuple[str, str, tuple[int, int, int], tuple[int, int, int]]] = [
    ("2026-04-18_01_conclusion", "まず結論", (99, 102, 241), (139, 92, 246)),
    ("2026-04-18_02_logging", "ログ出力の強化", (34, 197, 94), (16, 185, 129)),
    ("2026-04-18_04_timezone", "Windows・予約・タイムゾーン", (245, 158, 11), (251, 191, 36)),
    ("2026-04-18_05_bulk_delete", "一括削除の高速化", (239, 68, 68), (248, 113, 113)),
    ("2026-04-18_06_lazy_load", "画像の遅延ロード", (59, 130, 246), (96, 165, 250)),
    ("2026-04-18_07_impl_memo", "実装メモ", (148, 163, 184), (100, 116, 139)),
    ("2026-04-18_08_reflection", "振り返り", (168, 85, 247), (192, 132, 252)),
]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("meiryob.ttc", "meiryo.ttc", "YuGothB.ttc", "msgothic.ttc"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def gradient_vertical(
    draw: ImageDraw.ImageDraw, top: tuple[int, int, int], bottom: tuple[int, int, int]
) -> None:
    for y in range(H):
        t = y / max(H - 1, 1)
        r = int(top[0] * (1 - t) + bottom[0] * t)
        g = int(top[1] * (1 - t) + bottom[1] * t)
        b = int(top[2] * (1 - t) + bottom[2] * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))


def draw_soft_circle(
    draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, fill: tuple[int, int, int, int]
) -> None:
    bbox = (cx - r, cy - r, cx + r, cy + r)
    draw.ellipse(bbox, fill=fill)


def draw_decor(draw: ImageDraw.ImageDraw, stem: str, accent: tuple[int, int, int]) -> None:
    cx, cy = W // 2, int(H * 0.38)
    a = accent + (40,)
    draw_soft_circle(draw, cx, cy, 180, a)
    draw_soft_circle(draw, cx - 120, cy + 40, 60, accent + (25,))
    draw_soft_circle(draw, cx + 130, cy + 20, 45, accent + (30,))

    if "01_conclusion" in stem:
        # checkmarks / summary
        for i, (x0, y0) in enumerate([(cx - 80, cy - 30), (cx - 80, cy + 10), (cx - 80, cy + 50)]):
            draw.rounded_rectangle((x0, y0, x0 + 160, y0 + 28), radius=8, fill=(255, 255, 255, 55))
    elif "02_logging" in stem:
        # terminal lines
        for i in range(5):
            y = cy - 60 + i * 28
            w = 200 - i * 15
            draw.rounded_rectangle((cx - w // 2, y, cx + w // 2, y + 16), radius=4, fill=(15, 23, 42, 180))
    elif "04_timezone" in stem:
        # clock
        draw.ellipse((cx - 70, cy - 70, cx + 70, cy + 70), outline=(255, 255, 255, 200), width=6)
        for deg, ln in ((0, 45), (90, 35)):
            rad = math.radians(deg - 90)
            x2 = cx + int(ln * math.cos(rad))
            y2 = cy + int(ln * math.sin(rad))
            draw.line((cx, cy, x2, y2), fill=(255, 255, 255), width=5)
    elif "05_bulk_delete" in stem:
        for i in range(3):
            ox = i * 22 - 22
            draw.rounded_rectangle((cx - 50 + ox, cy - 40, cx + 50 + ox, cy + 50), radius=10, fill=(255, 255, 255, 70))
    elif "06_lazy_load" in stem:
        draw.rounded_rectangle((cx - 90, cy - 55, cx + 90, cy + 55), radius=12, outline=(255, 255, 255, 220), width=4)
        draw.ellipse((cx - 25, cy - 25, cx + 25, cy + 25), fill=(255, 255, 255, 90))
    elif "07_impl_memo" in stem:
        for row in range(3):
            for col in range(4):
                x1 = cx - 120 + col * 65
                y1 = cy - 50 + row * 40
                draw.rounded_rectangle((x1, y1, x1 + 55, y1 + 28), radius=4, fill=(255, 255, 255, 45))
    elif "08_reflection" in stem:
        draw.polygon(
            [(cx, cy - 70), (cx + 55, cy + 20), (cx - 55, cy + 20)],
            outline=(255, 255, 255, 230),
            width=5,
        )


def main() -> None:
    title_font = load_font(52)
    sub_font = load_font(22)

    for stem, title, ac1, ac2 in CHAPTERS:
        img = Image.new("RGBA", (W, H), (15, 23, 42, 255))
        draw = ImageDraw.Draw(img, "RGBA")
        gradient_vertical(draw, ac1, ac2)
        draw_decor(draw, stem, ac1)

        # vignette
        overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        od = ImageDraw.Draw(overlay, "RGBA")
        for y in range(H):
            edge = min(y, H - 1 - y) / (H * 0.5)
            alpha = int(80 * (1 - edge) ** 2)
            od.line([(0, y), (W, y)], fill=(0, 0, 0, alpha))
        img = Image.alpha_composite(img, overlay)
        draw = ImageDraw.Draw(img)

        tw, th = draw.textbbox((0, 0), title, font=title_font)[2:]
        tx = (W - tw) // 2
        ty = H - 130
        draw.text((tx + 3, ty + 3), title, font=title_font, fill=(0, 0, 0, 120))
        draw.text((tx, ty), title, font=title_font, fill=(248, 250, 252))

        sub = "Creator Portal 開発日誌 · 2026-04-18"
        sw = draw.textbbox((0, 0), sub, font=sub_font)[2]
        draw.text(((W - sw) // 2, ty + th + 12), sub, font=sub_font, fill=(226, 232, 240))

        out_path = OUT / f"{stem}.png"
        img.convert("RGB").save(out_path, "PNG", optimize=True)
        print("wrote", out_path)


if __name__ == "__main__":
    main()
