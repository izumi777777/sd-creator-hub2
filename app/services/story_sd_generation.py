"""ストーリー章 → Web UI txt2img → S3（original + stripped）→ Image 複数組。"""

from __future__ import annotations

import io
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

from flask import current_app
from werkzeug.utils import secure_filename

from app import db
from app.models.image import STORAGE_ORIGINAL, STORAGE_STRIPPED, Image
from app.services import image_metadata_service, s3_service
from app.services.chapter_image_overlay import (
    maybe_apply_story_text_overlay,
    resolve_chapter_story_overlay_texts,
)
from app.services.sd_webui_api import all_image_bytes, txt2img

if TYPE_CHECKING:
    from app.models.character import Character
    from app.models.story import Story

logger = logging.getLogger(__name__)

# Web UI / VRAM 負荷の上限（いずれかを満たすまで縮小はしない — 例外で拒否）
_MAX_STEPS = 200
_MAX_DIM = 4096
_MAX_BATCH = 16
_MAX_N_ITER = 32
_MAX_TOTAL_IMAGES = 40

# txt2img API の既定（Web UI の「普段」に寄せる）
DEFAULT_TXT2IMG_SAMPLER = "Euler a"
DEFAULT_CFG_SCALE = 7.0
_MIN_CFG = 1.0
_MAX_CFG = 30.0

# Hi-res fix（A1111 txt2img API: enable_hr, hr_scale, denoising_strength, …）
DEFAULT_HR_SCALE = 2.0
_MIN_HR_SCALE = 1.0
_MAX_HR_SCALE = 4.0
DEFAULT_HR_DENOISING = 0.5


def sanitize_enable_hr(value: Any) -> bool:
    """フォーム・DB から Hi-res fix オンオフを解釈する。"""
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(int(value))
    s = str(value).strip().lower()
    return s in ("1", "true", "on", "yes")


def sanitize_hr_scale(value: Any) -> float:
    if value is None or value == "":
        return DEFAULT_HR_SCALE
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_HR_SCALE
    if v != v:
        return DEFAULT_HR_SCALE
    return max(_MIN_HR_SCALE, min(v, _MAX_HR_SCALE))


def sanitize_hr_denoising_strength(value: Any) -> float:
    """Hi-res 2nd pass 用 denoising_strength（0〜1）。"""
    if value is None or value == "":
        return DEFAULT_HR_DENOISING
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_HR_DENOISING
    if v != v:
        return DEFAULT_HR_DENOISING
    return max(0.0, min(v, 1.0))


def sanitize_hr_second_pass_steps(value: Any) -> int:
    """0 のとき API では省略し、Web UI 既定（1st pass と同じ steps）に任せる。"""
    if value is None or value == "":
        return 0
    try:
        v = int(float(value))
    except (TypeError, ValueError):
        return 0
    return max(0, min(v, _MAX_STEPS))


def sanitize_hr_upscaler(name: Any) -> str | None:
    """空なら None（API に hr_upscaler を送らず Web UI 既定）。"""
    if name is None:
        return None
    s = str(name).strip()
    if not s:
        return None
    s = "".join(c for c in s if c.isprintable() and c not in "\r\n\t")
    return (s[:120] or None)


def sanitize_cfg_scale(value: Any) -> float:
    """CFG Scale を API 用にクランプする。"""
    if value is None or value == "":
        return DEFAULT_CFG_SCALE
    try:
        v = float(value)
    except (TypeError, ValueError):
        return DEFAULT_CFG_SCALE
    if v != v:  # NaN
        return DEFAULT_CFG_SCALE
    return max(_MIN_CFG, min(v, _MAX_CFG))


def sanitize_sampler_name(name: Any) -> str:
    """sampler_name を API 用に正規化（空なら Euler a）。"""
    if name is None:
        return DEFAULT_TXT2IMG_SAMPLER
    s = str(name).strip()
    if not s:
        return DEFAULT_TXT2IMG_SAMPLER
    s = "".join(c for c in s if c.isprintable() and c not in "\r\n\t")
    return (s or DEFAULT_TXT2IMG_SAMPLER)[:80]


def _mime_and_ext(data: bytes) -> tuple[str, str]:
    if len(data) >= 2 and data[:2] == b"\xff\xd8":
        return "image/jpeg", ".jpg"
    return "image/png", ".png"


def _chapter_no(ch: dict, index: int) -> int:
    raw = ch.get("no")
    try:
        return int(raw) if raw is not None else index + 1
    except (TypeError, ValueError):
        return index + 1


def resolve_chapter_prompt_neg(
    chapters: list[dict[str, Any]],
    ch_no: int,
    variant_index: int | None,
) -> tuple[str, str]:
    """シーン番号と任意の variant インデックスから positive / negative を返す。"""
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        if _chapter_no(ch, i) != ch_no:
            continue
        variants = ch.get("prompt_variants")
        if (
            variant_index is not None
            and isinstance(variants, list)
            and 0 <= variant_index < len(variants)
        ):
            v = variants[variant_index]
            if not isinstance(v, dict):
                break
            return (str(v.get("prompt") or "").strip(), str(v.get("neg") or "").strip())
        return (str(ch.get("prompt") or "").strip(), str(ch.get("neg") or "").strip())
    raise ValueError(f"シーン番号 {ch_no} が見つかりません。")


def _checkpoint_name(character: Character) -> str:
    raw = (character.sd_model or "").strip()
    if raw:
        if not raw.lower().endswith((".safetensors", ".ckpt")):
            return f"{raw}.safetensors"
        return raw
    default = (current_app.config.get("SD_WEBUI_DEFAULT_CHECKPOINT") or "").strip()
    if not default:
        raise ValueError(
            "キャラクターの「使用SDモデル」が空です。"
            " マスタを設定するか、.env の SD_WEBUI_DEFAULT_CHECKPOINT を設定してください。"
        )
    if not default.lower().endswith((".safetensors", ".ckpt")):
        return f"{default}.safetensors"
    return default


def _with_lora(prompt: str, character: Character) -> str:
    if not bool(current_app.config.get("SD_TXT2IMG_APPEND_LORA", True)):
        return prompt
    name = (character.lora_name or "").strip()
    if not name:
        return prompt
    w = character.lora_weight
    try:
        wf = float(w) if w is not None else 0.8
    except (TypeError, ValueError):
        wf = 0.8
    tag = f"<lora:{name}:{wf:.2f}>"
    if tag in prompt or f"<lora:{name}:" in prompt:
        return prompt
    return f"{prompt.rstrip()}, {tag}".strip().strip(",").strip()


def _grid_align_for_checkpoint(ckpt: str) -> int:
    """
    幅・高さを揃えるピクセルグリッド（8 / 16 / 32 / 64）。
    SDXL 系は 64 未満の端数だけ揃えると潜在とズレてノイズ・崩れが出やすい。
    """
    raw = (current_app.config.get("SD_TXT2IMG_GRID_ALIGN") or "").strip().lower()
    if raw in ("8", "16", "32", "64"):
        return int(raw)
    low = (ckpt or "").lower()
    if any(x in low for x in ("xl", "sdxl", "playground", "chroma")):
        return 64
    return 8


def _dim_for_txt2img(x: int, *, grid: int = 8) -> int:
    """grid ピクセル倍数に最も近い解像度へ（round）。Web UI のスライダー挙動に近づける。"""
    g = max(8, min(int(grid), 128))
    xi = max(64, min(int(x), _MAX_DIM))
    k = max(1, round(xi / g))
    out = k * g
    return max(64, min(out, _MAX_DIM))


def normalize_batch_n_iter(batch_size: int | None, n_iter: int | None) -> tuple[int, int]:
    """batch_size / n_iter を検証し、合計枚数の上限内に収める。"""
    bs = max(1, min(int(batch_size or 1), _MAX_BATCH))
    ni = max(1, min(int(n_iter or 1), _MAX_N_ITER))
    total = bs * ni
    if total > _MAX_TOTAL_IMAGES:
        raise ValueError(
            f"生成枚数（batch_size × n_iter）は最大 {_MAX_TOTAL_IMAGES} までです。"
            f"（現在の積: {total}）"
        )
    return bs, ni


def build_txt2img_payload(
    character: Character,
    prompt: str,
    negative: str,
    *,
    steps: int,
    width: int,
    height: int,
    seed: int,
    batch_size: int = 1,
    n_iter: int = 1,
    cfg_scale: Any = None,
    sampler_name: Any = None,
    enable_hr: Any = None,
    hr_scale: Any = None,
    hr_denoising_strength: Any = None,
    hr_second_pass_steps: Any = None,
    hr_upscaler: Any = None,
) -> dict[str, Any]:
    bs, ni = normalize_batch_n_iter(batch_size, n_iter)
    ckpt = _checkpoint_name(character)
    grid = _grid_align_for_checkpoint(ckpt)
    w = _dim_for_txt2img(width, grid=grid)
    h = _dim_for_txt2img(height, grid=grid)
    if int(width) != w or int(height) != h:
        logger.info(
            "story_sd_generation: txt2img snapped WxH %sx%s -> %sx%s (grid=%s, ckpt=%s)",
            width,
            height,
            w,
            h,
            grid,
            ckpt,
        )
    cfg = sanitize_cfg_scale(cfg_scale)
    sampler = sanitize_sampler_name(sampler_name)
    payload: dict[str, Any] = {
        "prompt": _with_lora(prompt, character),
        "negative_prompt": negative,
        "steps": max(1, min(int(steps), _MAX_STEPS)),
        "width": w,
        "height": h,
        "cfg_scale": cfg,
        "sampler_name": sampler,
        "batch_size": bs,
        "n_iter": ni,
        "override_settings": {"sd_model_checkpoint": ckpt},
    }
    if seed is not None and seed >= 0:
        payload["seed"] = seed

    if sanitize_enable_hr(enable_hr):
        payload["enable_hr"] = True
        payload["hr_scale"] = sanitize_hr_scale(hr_scale)
        payload["denoising_strength"] = sanitize_hr_denoising_strength(hr_denoising_strength)
        hr2 = sanitize_hr_second_pass_steps(hr_second_pass_steps)
        if hr2 > 0:
            payload["hr_second_pass_steps"] = hr2
        hu = sanitize_hr_upscaler(hr_upscaler)
        if hu:
            payload["hr_upscaler"] = hu
    else:
        payload["enable_hr"] = False
    return payload


def generate_chapter_images(
    story: Story,
    character: Character,
    ch_no: int,
    variant_index: int | None,
    *,
    steps: int,
    width: int,
    height: int,
    seed: int,
    batch_size: int = 1,
    n_iter: int = 1,
    cfg_scale: Any = None,
    sampler_name: Any = None,
    enable_hr: Any = None,
    hr_scale: Any = None,
    hr_denoising_strength: Any = None,
    hr_second_pass_steps: Any = None,
    hr_upscaler: Any = None,
    overlay_include_top_story: bool = True,
    overlay_include_speech: bool = True,
    speech_bottom_override: str | None = None,
) -> list[tuple[Image, Image]]:
    """
    Web UI で txt2img し、返却された各画像について
    メタ付き原本 + メタ除去版を S3 に置き、(Image, Image) のタプルを枚数分返す。

    overlay_include_top_story が False のとき、上段（title/scene）を載せない。
    overlay_include_speech が False のとき、下段の speech を載せない。
    speech_bottom_override が非空のとき、下段は章の speech の代わりにその文字列を使う。
    """
    if story.character_id != character.id:
        raise ValueError("ストーリーとキャラクターが一致しません。")
    base_url = (current_app.config.get("SD_WEBUI_BASE_URL") or "").strip().rstrip("/")
    if not base_url:
        raise ValueError("SD_WEBUI_BASE_URL が未設定です。")
    if not s3_service.is_s3_configured():
        raise ValueError("S3 が未設定です。")

    chapters = story.get_chapters()
    pos, neg = resolve_chapter_prompt_neg(chapters, ch_no, variant_index)
    if not pos.strip():
        raise ValueError("このシーンの Positive（プロンプト）が空です。")

    bs, ni = normalize_batch_n_iter(batch_size, n_iter)
    payload = build_txt2img_payload(
        character,
        pos,
        neg,
        steps=steps,
        width=width,
        height=height,
        seed=seed,
        batch_size=bs,
        n_iter=ni,
        cfg_scale=cfg_scale,
        sampler_name=sampler_name,
        enable_hr=enable_hr,
        hr_scale=hr_scale,
        hr_denoising_strength=hr_denoising_strength,
        hr_second_pass_steps=hr_second_pass_steps,
        hr_upscaler=hr_upscaler,
    )
    base_timeout = float(current_app.config.get("SD_WEBUI_TIMEOUT") or 600)
    # 多枚・高ステップは API が長くなるため上限付きで延長
    timeout = min(3600.0, base_timeout + 45.0 * (bs * ni) + 2.0 * max(0, int(payload["steps"]) - 20))
    if payload.get("enable_hr"):
        timeout = min(3600.0, timeout + 120.0 + 30.0 * max(0, int(payload.get("hr_second_pass_steps") or payload["steps"]) - 15))

    pos_s = str(pos)
    logger.info("=" * 50)
    logger.info(
        "画像生成 開始 | story_id=%s | ch=%s | variant=%s",
        story.id,
        ch_no,
        variant_index,
    )
    logger.info(
        "  キャラ    : %s (id=%s)",
        character.name,
        character.id,
    )
    logger.info(
        "  モデル    : %s",
        payload.get("override_settings", {}).get("sd_model_checkpoint", "unknown"),
    )
    logger.info(
        "  サイズ    : %sx%s  steps=%s  cfg=%s  sampler=%s",
        payload["width"],
        payload["height"],
        payload["steps"],
        payload.get("cfg_scale"),
        payload.get("sampler_name"),
    )
    logger.info(
        "  バッチ    : batch=%s × n_iter=%s = 合計%s枚",
        bs,
        ni,
        bs * ni,
    )
    if payload.get("enable_hr"):
        logger.info(
            "  Hi-res fix: ON | scale=%s | denoise=%s | 2nd_steps=%s",
            payload.get("hr_scale"),
            payload.get("denoising_strength"),
            payload.get("hr_second_pass_steps", 0),
        )
    logger.info(
        "  Positive  : %s...",
        pos_s[:100],
    )
    logger.info(
        "  Web UI URL: %s",
        base_url,
    )

    api_start = time.perf_counter()
    logger.info("  Web UI API 呼び出し中...")

    try:
        raw_response = txt2img(base_url, payload, timeout=timeout)
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - api_start) * 1000)
        logger.error(
            "画像生成 失敗 ✗ | story_id=%s ch=%s | %dms | %s",
            story.id,
            ch_no,
            elapsed_ms,
            e,
        )
        raise

    api_ms = int((time.perf_counter() - api_start) * 1000)
    originals = all_image_bytes(raw_response)
    logger.info(
        "  Web UI 完了 ✓ | %d枚受信 | %dms",
        len(originals),
        api_ms,
    )
    overlay_enabled = bool(current_app.config.get("STORY_IMAGE_TEXT_OVERLAY", True))
    overlay_font = current_app.config.get("STORY_OVERLAY_FONT_PATH")
    overlay_font_s = overlay_font if isinstance(overlay_font, str) else None
    top_overlay, bottom_overlay = resolve_chapter_story_overlay_texts(
        chapters, ch_no, variant_index, include_chapter_title=True
    )
    if not overlay_include_top_story:
        top_overlay = ""
    if (
        overlay_include_speech
        and speech_bottom_override is not None
        and str(speech_bottom_override).strip()
    ):
        bottom_overlay = str(speech_bottom_override).strip()
    if not overlay_include_speech:
        bottom_overlay = ""

    out: list[tuple[Image, Image]] = []
    prefix = secure_filename(character.name) or f"char_{character.id}"
    vpart = f"v{variant_index}" if variant_index is not None else "main"
    run_uid = uuid.uuid4().hex[:10]

    upload_start = time.perf_counter()
    for idx, original_bytes in enumerate(originals):
        logger.info(
            "  S3 保存中 [%d/%d] original + stripped...",
            idx + 1,
            len(originals),
        )
        if overlay_enabled and (top_overlay or bottom_overlay):
            original_bytes = maybe_apply_story_text_overlay(
                original_bytes,
                top_text=top_overlay,
                bottom_text=bottom_overlay,
                enabled=True,
                font_path=overlay_font_s,
            )
        stripped_bytes = image_metadata_service.strip_metadata_from_bytes(original_bytes)
        orig_ct, orig_ext = _mime_and_ext(original_bytes)
        strip_ct, strip_ext = _mime_and_ext(stripped_bytes)
        piece = f"{run_uid}_{idx}"
        base_orig = f"story{story.id}_ch{ch_no}_{vpart}_{piece}{orig_ext}"
        base_strip = f"story{story.id}_ch{ch_no}_{vpart}_{piece}{strip_ext}"

        key_orig = f"{prefix}/{STORAGE_ORIGINAL}/{base_orig}"
        key_strip = f"{prefix}/{STORAGE_STRIPPED}/{base_strip}"

        url_orig = s3_service.upload_file(
            io.BytesIO(original_bytes), key_orig, content_type=orig_ct
        )
        url_strip = s3_service.upload_file(
            io.BytesIO(stripped_bytes), key_strip, content_type=strip_ct
        )

        img_orig = Image(
            character_id=character.id,
            story_id=story.id,
            work_id=None,
            storage_folder=STORAGE_ORIGINAL,
            s3_key=key_orig,
            s3_url=url_orig,
            file_name=base_orig,
            file_size=len(original_bytes),
        )
        img_strip = Image(
            character_id=character.id,
            story_id=story.id,
            work_id=None,
            storage_folder=STORAGE_STRIPPED,
            s3_key=key_strip,
            s3_url=url_strip,
            file_name=base_strip,
            file_size=len(stripped_bytes),
        )
        db.session.add(img_orig)
        db.session.add(img_strip)
        out.append((img_orig, img_strip))

    upload_ms = int((time.perf_counter() - upload_start) * 1000)
    total_ms = api_ms + upload_ms

    logger.info(
        "画像生成 完了 ✓ | story_id=%s ch=%s | "
        "生成%d枚 → S3保存%d件 | WebUI:%dms S3:%dms 合計:%dms",
        story.id,
        ch_no,
        len(originals),
        len(originals) * 2,
        api_ms,
        upload_ms,
        total_ms,
    )
    logger.info("=" * 50)

    db.session.commit()
    return out
