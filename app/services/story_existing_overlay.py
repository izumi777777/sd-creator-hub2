"""既存のストーリー画像に章テキストを焼き込み、別 S3 オブジェクト＋ Image 行として追加する。"""

from __future__ import annotations

import io
import logging
import re
import uuid
from typing import TYPE_CHECKING

from flask import current_app
from werkzeug.utils import secure_filename

from app import db
from app.models.image import STORAGE_TEXT_OVERLAY, Image
from app.services import s3_service
from app.services.chapter_image_overlay import (
    maybe_apply_story_text_overlay,
    resolve_chapter_story_overlay_texts,
)

if TYPE_CHECKING:
    from app.models.story import Story

logger = logging.getLogger(__name__)

_STORY_FN_CH = re.compile(r"_ch(\d+)_", re.IGNORECASE)
_STORY_FN_V = re.compile(r"_v(\d+)_", re.IGNORECASE)


def guess_chapter_variant_from_story_filename(file_name: str) -> tuple[int | None, int | None]:
    """
    章生成時のファイル名（例: story12_ch3_v0_xxx.png）からシーン番号・variant を推測する。
    _main_ のときは variant は None。
    """
    fn = file_name or ""
    ch_m = _STORY_FN_CH.search(fn)
    ch_no = int(ch_m.group(1)) if ch_m else None
    if "_main_" in fn.lower():
        return ch_no, None
    v_m = _STORY_FN_V.search(fn)
    if v_m:
        return ch_no, int(v_m.group(1))
    return ch_no, None


def create_text_overlay_copy_for_story_image(
    *,
    story: "Story",
    source: Image,
    ch_no: int | None,
    variant_index: int | None,
    overlay_include_speech: bool,
    include_chapter_title: bool = True,
    overlay_include_top_story: bool = True,
    speech_bottom_override: str | None = None,
) -> Image:
    """
    元の Image / S3 は変更せず、テキスト焼き込み版を text_overlay に保存して新規 Image を返す。

    Raises:
        ValueError: 前提不備・焼き込み対象テキストなし・オーバーレイ失敗など
    """
    if not s3_service.is_s3_configured():
        raise ValueError("S3 が未設定のためダウンロード・アップロードできません。")
    key = (source.s3_key or "").strip()
    if not key:
        raise ValueError("元画像に S3 キーがありません。")
    if (source.storage_folder or "").strip() == STORAGE_TEXT_OVERLAY:
        raise ValueError("テキスト焼き増し版をさらに焼き増しすることはできません（元画像を選んでください）。")

    if not bool(current_app.config.get("STORY_IMAGE_TEXT_OVERLAY", True)):
        raise ValueError(
            "テキスト焼き込みは無効です（.env の STORY_IMAGE_TEXT_OVERLAY=0）。"
            " 有効にしてから再度お試しください。"
        )

    chapters = story.get_chapters()
    g_ch, g_v = guess_chapter_variant_from_story_filename(source.file_name or "")
    use_ch = ch_no if ch_no is not None and ch_no >= 1 else g_ch
    if use_ch is None or use_ch < 1:
        raise ValueError(
            "シーン番号が分かりません。フォームにシーン番号を入力するか、"
            "ファイル名が story…_ch◯_… 形式であることを確認してください。"
        )
    use_v = variant_index if variant_index is not None else g_v

    top, bottom = resolve_chapter_story_overlay_texts(
        chapters,
        use_ch,
        use_v,
        include_chapter_title=include_chapter_title,
    )
    if not overlay_include_top_story:
        top = ""
    if (
        overlay_include_speech
        and speech_bottom_override is not None
        and speech_bottom_override.strip()
    ):
        bottom = speech_bottom_override.strip()
    if not overlay_include_speech:
        bottom = ""
    if not (top or bottom).strip():
        raise ValueError(
            f"シーン {use_ch} に焼き込むテキストがありません。"
            " 上段ストーリーをオフにした場合はセリフ（またはプリセット）が必要です。"
            " 上段オンで「見出しを入れない」のときは要約（scene）が必要です。"
            " 章の title / scene / speech、およびフォームの選択を確認してください。"
        )

    raw_bytes = s3_service.download_object_bytes_with_image_fallbacks(
        key,
        file_name=source.file_name,
        s3_url=source.s3_url,
    )
    font_path = current_app.config.get("STORY_OVERLAY_FONT_PATH")
    font_s = font_path if isinstance(font_path, str) else None
    out_bytes = maybe_apply_story_text_overlay(
        raw_bytes,
        top_text=top,
        bottom_text=bottom,
        enabled=True,
        font_path=font_s,
    )
    if out_bytes == raw_bytes:
        raise ValueError("オーバーレイ後の画像が元と同一のため保存しませんでした（フォント・画像形式を確認してください）。")

    character = story.character
    if not character or source.character_id != character.id:
        raise ValueError("ストーリーと画像のキャラクターが一致しません。")
    prefix = secure_filename(character.name) or f"char_{character.id}"
    base_stem = (source.file_name or "image").rsplit(".", 1)[0]
    safe_stem = secure_filename(base_stem) or "image"
    piece = uuid.uuid4().hex[:10]
    out_name = f"{safe_stem}_textlayer_{piece}.png"
    s3_key = f"{prefix}/{STORAGE_TEXT_OVERLAY}/{out_name}"

    url = s3_service.upload_file(
        io.BytesIO(out_bytes),
        s3_key,
        content_type="image/png",
    )
    new_img = Image(
        character_id=character.id,
        work_id=None,
        story_id=story.id,
        storage_folder=STORAGE_TEXT_OVERLAY,
        s3_key=s3_key,
        s3_url=url,
        file_name=out_name,
        file_size=len(out_bytes),
    )
    db.session.add(new_img)
    db.session.commit()
    logger.info(
        "story_existing_overlay: created text_overlay id=%s from source=%s story=%s ch=%s v=%s",
        new_img.id,
        source.id,
        story.id,
        use_ch,
        use_v,
    )
    return new_img
