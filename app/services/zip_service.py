"""画像 URL から ZIP を生成する。"""

import base64
import io
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Literal

import requests

FolderStructure = Literal["flat", "by_character", "numbered"]


def generate_zip(
    images: list[dict[str, Any]],
    structure: FolderStructure = "flat",
) -> bytes:
    """
    画像情報のリストから ZIP を生成する。
    HTTP 画像の取得は ThreadPoolExecutor で並列化する。

    Args:
        images: 各要素は url, name, character_name（任意）を想定
        structure: flat / by_character / numbered

    Returns:
        ZIP のバイト列
    """
    img_data_map: dict[int, bytes | None] = {}
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_idx = {
            executor.submit(_fetch_image, str(images[i]["url"])): i
            for i in range(len(images))
        }
        for fut in as_completed(future_to_idx):
            idx = future_to_idx[fut]
            img_data_map[idx] = fut.result()

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for i, image in enumerate(images):
            img_data = img_data_map.get(i)
            if img_data is None:
                continue
            file_path = _build_path(image, i, structure)
            zf.writestr(file_path, img_data)
    zip_buffer.seek(0)
    return zip_buffer.getvalue()


def _fetch_image(url: str) -> bytes | None:
    """URL または data URL から画像バイト列を取得する。"""
    try:
        if url.startswith("data:"):
            _prefix, data = url.split(",", 1)
            return base64.b64decode(data)
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception:
        return None


def _build_path(image: dict[str, Any], index: int, structure: str) -> str:
    """ZIP 内のファイルパスを決める。"""
    name = image.get("name") or f"image_{index + 1}.png"
    char = image.get("character_name") or "unknown"

    if structure == "flat":
        return str(name)
    if structure == "by_character":
        return f"{char}/{name}"
    if structure == "numbered":
        return f"{str(index + 1).zfill(3)}_{name}"
    return str(name)
