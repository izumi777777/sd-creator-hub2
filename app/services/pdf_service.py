"""画像 URL リストから PDF を生成する（fpdf2 + Pillow）。"""

import base64
import io
from typing import Literal

import requests
from fpdf import FPDF
from PIL import Image as PILImage

PageSize = Literal["a4", "a5", "b5", "square"]
FitMode = Literal["fit", "fill", "full"]

PAGE_SIZES: dict[str, tuple[float, float]] = {
    "a4": (210, 297),
    "a5": (148, 210),
    "b5": (176, 250),
    "square": (150, 150),
}


def generate_pdf(
    image_urls: list[str],
    page_size: PageSize = "a4",
    fit_mode: FitMode = "fit",
    bg_color: str = "white",
) -> bytes:
    """
    画像リストから PDF を生成してバイト列で返す。

    Args:
        image_urls: 画像 URL または data URL のリスト
        page_size: a4 / a5 / b5 / square
        fit_mode: fit / fill / full
        bg_color: white / black

    Returns:
        PDF のバイト列
    """
    pw, ph = PAGE_SIZES.get(page_size, PAGE_SIZES["a4"])
    bg_rgb = (0, 0, 0) if bg_color == "black" else (255, 255, 255)

    pdf = FPDF(orientation="P", unit="mm", format=(pw, ph))
    pdf.set_auto_page_break(False)

    for url in image_urls:
        pdf.add_page()
        pdf.set_fill_color(*bg_rgb)
        pdf.rect(0, 0, pw, ph, "F")

        img_data = _load_image(url)
        if img_data is None:
            continue

        x, y, w, h = _calc_position(img_data, pw, ph, fit_mode)
        # fpdf2 は一時ファイルまたはパスが安定しやすいため BytesIO を渡す
        with io.BytesIO(img_data) as img_buffer:
            pdf.image(img_buffer, x=x, y=y, w=w, h=h)

    # dest='S' でバイト列または str を返す（バージョン依存のため両対応）
    out = pdf.output(dest="S")
    if isinstance(out, str):
        return out.encode("latin-1")
    return bytes(out)


def _load_image(source: str) -> bytes | None:
    """URL または data URL から画像バイト列を取得する。"""
    try:
        if source.startswith("data:"):
            _header, data = source.split(",", 1)
            return base64.b64decode(data)
        response = requests.get(source, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def _calc_position(
    img_data: bytes, pw: float, ph: float, fit_mode: str
) -> tuple[float, float, float, float]:
    """画像の配置位置とサイズ（mm）を計算する。"""
    with PILImage.open(io.BytesIO(img_data)) as img:
        iw, ih = img.size
    ratio = iw / ih

    if fit_mode == "fit":
        w = pw
        h = pw / ratio
        if h > ph:
            h = ph
            w = ph * ratio
        x = (pw - w) / 2
        y = (ph - h) / 2
    elif fit_mode == "fill":
        w = pw
        h = pw / ratio
        if h < ph:
            h = ph
            w = ph * ratio
        x = (pw - w) / 2
        y = (ph - h) / 2
    else:
        x, y, w, h = 0.0, 0.0, pw, ph

    return x, y, w, h
