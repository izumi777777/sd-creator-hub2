"""章の title/scene（上段）と speech（下段）を生成画像に焼き込む。"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Any

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

_LINE_SPACING = 1.4
_TEXT_MARGIN_RATIO = 0.06  # 画像幅に対する左右余白
_MAX_TOP_LINES = 16
_MAX_BOTTOM_LINES = 12  # フォント縮小で行数が増えうるため余裕を持つ


def _default_font_candidates() -> list[str]:
    return [
        "C:/Windows/Fonts/meiryo.ttc",
        "C:/Windows/Fonts/meiryob.ttc",
        "C:/Windows/Fonts/msgothic.ttc",
        "C:/Windows/Fonts/yu_gothic.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    ]


def _load_font(path: str | None, size: int) -> ImageFont.ImageFont:
    if path:
        p = path.strip()
        if p:
            try:
                return ImageFont.truetype(p, size)
            except OSError:
                logger.warning("chapter_image_overlay: 指定フォントを開けません: %s", p)
    for fb in _default_font_candidates():
        try:
            return ImageFont.truetype(fb, size)
        except OSError:
            continue
    logger.warning("chapter_image_overlay: 日本語フォントが見つかりません。ビットマップフォントにフォールバックします。")
    return ImageFont.load_default()


@lru_cache(maxsize=32)
def _load_font_cached(path: str | None, size: int) -> ImageFont.ImageFont:
    """同じ path + size のフォントはディスクから1回だけ読み込む。"""
    return _load_font(path, size)


def _text_line_width(draw: ImageDraw.ImageDraw, line: str, font: ImageFont.ImageFont) -> float:
    """1 行の描画幅（px）。Pillow の textlength / textbbox にフォールバック。"""
    if not line:
        return 0.0
    try:
        return float(draw.textlength(line, font=font))
    except Exception:
        try:
            b = draw.textbbox((0, 0), line, font=font)
            return float(b[2] - b[0])
        except Exception:
            fs = int(getattr(font, "size", 16))
            return len(line) * fs * 0.62


def _wrap_block_to_max_pixel_width(
    text: str,
    font: ImageFont.ImageFont,
    max_w: float,
    draw: ImageDraw.ImageDraw,
) -> list[str]:
    """
    改行で段落分けし、各段落を 1 文字ずつ積んで max_w を超えたら改行（日本語のはみ出し防止）。
    """
    lines_out: list[str] = []
    for para in (text or "").split("\n"):
        p = para.strip()
        if not p:
            continue
        current = ""
        for ch in p:
            test = current + ch
            if _text_line_width(draw, test, font) <= max_w:
                current = test
            else:
                if current:
                    lines_out.append(current)
                    current = ch
                    if _text_line_width(draw, current, font) > max_w:
                        lines_out.append(current)
                        current = ""
                else:
                    lines_out.append(ch)
                    current = ""
        if current:
            lines_out.append(current)
    return lines_out if lines_out else ([] if not (text or "").strip() else [""])


def _draw_text_band(
    overlay: Image.Image,
    y_start: int,
    height: int,
    text_lines: list[str],
    font: ImageFont.ImageFont,
    bg_color: tuple[int, int, int, int],
    text_color: tuple[int, int, int],
    margin: int,
    line_spacing: float,
    img_width: int,
) -> None:
    band = Image.new("RGBA", (img_width, height), bg_color)
    overlay.paste(band, (0, y_start), band)
    draw_overlay = ImageDraw.Draw(overlay)
    try:
        font_px = int(getattr(font, "size", 16))
    except (TypeError, ValueError):
        font_px = 16
    line_h = max(12, int(font_px * line_spacing))
    y = y_start + max(8, (height - line_h * len(text_lines)) // 2)
    fill_rgba = (*text_color, 255)
    for line in text_lines:
        draw_overlay.text((margin, y), line, font=font, fill=fill_rgba)
        y += line_h


def _compose_overlay_rgba(
    base_rgba: Image.Image,
    top_text: str,
    bottom_text: str,
    font_path: str | None,
) -> Image.Image:
    img_w, img_h = base_rgba.size
    margin = max(12, int(img_w * _TEXT_MARGIN_RATIO))
    max_text_w = float(max(32, img_w - 2 * margin - 4))

    narr_size = max(15, min(26, img_w // 22))
    # セリフは既定をやや小さくし、ピクセル折り返し＋フォント縮小で帯内に収める
    dial_max = max(18, min(36, img_w // 18))

    font_top = _load_font_cached(font_path, narr_size)
    measure_draw = ImageDraw.Draw(Image.new("RGB", (max(int(max_text_w) + 8, 64), 64)))

    overlay = base_rgba.copy()
    top_bg = (0, 0, 0, 168)
    top_fg = (235, 235, 235)
    bot_bg = (20, 10, 40, 188)
    # 下段セリフ文字色（濃い帯上で読めるピンク）
    bot_fg = (255, 168, 218)

    if top_text:
        narr_lines = _wrap_block_to_max_pixel_width(
            top_text, font_top, max_text_w, measure_draw
        )
        if len(narr_lines) > _MAX_TOP_LINES:
            narr_lines = narr_lines[: _MAX_TOP_LINES - 1]
            narr_lines.append("…")
        try:
            font_px = int(getattr(font_top, "size", narr_size))
        except (TypeError, ValueError):
            font_px = narr_size
        line_h = max(12, int(font_px * _LINE_SPACING))
        band_h = min(int(img_h * 0.42), line_h * len(narr_lines) + 28)
        _draw_text_band(
            overlay,
            0,
            band_h,
            narr_lines,
            font_top,
            top_bg,
            top_fg,
            margin,
            _LINE_SPACING,
            img_w,
        )

    if bottom_text:
        max_band_h = int(img_h * 0.32)
        dial_lines: list[str] = []
        font_bottom: ImageFont.ImageFont | None = None
        line_h = 14
        dial_start = max(10, dial_max)
        for fs in range(dial_start, 8, -1):
            font_bottom = _load_font_cached(font_path, fs)
            dial_lines = _wrap_block_to_max_pixel_width(
                bottom_text.strip(), font_bottom, max_text_w, measure_draw
            )
            if len(dial_lines) > _MAX_BOTTOM_LINES:
                dial_lines = dial_lines[: _MAX_BOTTOM_LINES - 1]
                dial_lines.append("…")
            try:
                font_px = int(getattr(font_bottom, "size", fs))
            except (TypeError, ValueError):
                font_px = fs
            line_h = max(11, int(font_px * _LINE_SPACING))
            need_h = line_h * len(dial_lines) + 28
            if need_h <= max_band_h + 8:
                break
        if font_bottom is None:
            font_bottom = _load_font_cached(font_path, 10)
            dial_lines = _wrap_block_to_max_pixel_width(
                bottom_text.strip(), font_bottom, max_text_w, measure_draw
            )[:_MAX_BOTTOM_LINES]

        band_h = min(max_band_h + 12, line_h * len(dial_lines) + 32)
        _draw_text_band(
            overlay,
            img_h - band_h,
            band_h,
            dial_lines,
            font_bottom,
            bot_bg,
            bot_fg,
            margin,
            _LINE_SPACING,
            img_w,
        )

    return overlay


def maybe_apply_story_text_overlay(
    image_bytes: bytes,
    *,
    top_text: str,
    bottom_text: str,
    enabled: bool,
    font_path: str | None,
) -> bytes:
    """
    title/scene 相当（上）と speech（下）を画像に重ね、PNG または JPEG バイト列で返す。
    無効・本文なし・失敗時は元バイト列をそのまま返す。
    """
    if not enabled:
        return image_bytes
    top = (top_text or "").strip()
    bottom = (bottom_text or "").strip()
    if not top and not bottom:
        return image_bytes

    try:
        bio_in = io.BytesIO(image_bytes)
        with Image.open(bio_in) as im:
            im.load()
            is_jpeg = im.format == "JPEG" or (len(image_bytes) >= 2 and image_bytes[:2] == b"\xff\xd8")
            base = im.convert("RGBA")
        composed = _compose_overlay_rgba(base, top, bottom, font_path)
        rgb = composed.convert("RGB")
        out = io.BytesIO()
        if is_jpeg:
            rgb.save(out, format="JPEG", quality=95, optimize=True)
        else:
            rgb.save(out, format="PNG", optimize=True)
        return out.getvalue()
    except Exception:
        logger.exception("chapter_image_overlay: オーバーレイ失敗のため元画像を保存します")
        return image_bytes


def _chapter_no(ch: dict[str, Any], index: int) -> int:
    """resolve_chapter_prompt_neg と同じシーン番号の解釈。"""
    raw = ch.get("no")
    try:
        return int(raw) if raw is not None else index + 1
    except (TypeError, ValueError):
        return index + 1


def resolve_chapter_story_overlay_texts(
    chapters: list[dict[str, Any]],
    ch_no: int,
    variant_index: int | None,
    *,
    include_chapter_title: bool = True,
) -> tuple[str, str]:
    """
    章 JSON から (上段ストーリー, 下段セリフ) を返す。
    上段: 既定では title と scene を改行で連結。include_chapter_title=False のときは scene のみ（要約のみ）。
    下段: 指定 variant の speech → 章直下の speech → 未指定で variants があるときは先頭パターンの speech
    （ファイル名 _main_ 等で variant が None でも、UI で保存したセリフが v0 にあるケースを拾う）。
    """
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        if _chapter_no(ch, i) != ch_no:
            continue
        title = str(ch.get("title") or "").strip()
        scene = str(ch.get("scene") or "").strip()
        if include_chapter_title:
            if title and scene:
                top = f"{title}\n{scene}"
            else:
                top = title or scene
        else:
            top = scene

        bottom = ""
        variants = ch.get("prompt_variants")
        if (
            variant_index is not None
            and isinstance(variants, list)
            and 0 <= variant_index < len(variants)
        ):
            v = variants[variant_index]
            if isinstance(v, dict):
                bottom = str(v.get("speech") or "").strip()
        if not bottom:
            bottom = str(ch.get("speech") or "").strip()
        if not bottom and isinstance(variants, list) and variants:
            v0 = variants[0]
            if isinstance(v0, dict):
                bottom = str(v0.get("speech") or "").strip()
        return (top, bottom)

    return ("", "")
