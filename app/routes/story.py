"""ストーリー生成・保存（Gemini + htmx）。"""

import json
import logging
from datetime import date, datetime

from flask import (
    Blueprint,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from app import db
from app.models.character import Character
from app.models.image import Image
from app.models.prompt import Prompt
from app.models.scheduled_image_job import ScheduledImageJob
from app.models.story import (
    Story,
    resolve_speech_bottom_override,
    set_chapter_speech_presets,
)
from app.prompts.story_prompt import STORY_SYSTEM_PROMPT
from app.prompts.story_recharacterize_prompt import (
    STORY_RECHARACTERIZE_SYSTEM_PROMPT,
)
from app.prompts.story_revise_prompt import STORY_REVISE_SYSTEM_PROMPT
from app.services.gemini_service import call_gemini_json
from app.services.seasonal_story import (
    build_seasonal_user_addon,
    parse_seasonal_form,
    seasonal_summary_line,
    week_of_month,
)
from app.services import s3_service
from app.services.schedule_timezone import parse_scheduled_at_to_utc_naive
from app.services.pixiv_text import (
    first_japanese_title_candidate,
    sanitize_markdown_for_pixiv,
    split_gemini_pixiv_sections,
    tags_block_to_pixiv_lines,
)
from app.services.story_existing_overlay import (
    create_text_overlay_copy_for_story_image,
    guess_chapter_variant_from_story_filename,
)
from app.services.story_sd_generation import (
    generate_chapter_images,
    normalize_batch_n_iter,
    sanitize_cfg_scale,
    sanitize_enable_hr,
    sanitize_hr_denoising_strength,
    sanitize_hr_scale,
    sanitize_hr_second_pass_steps,
    sanitize_hr_upscaler,
    sanitize_sampler_name,
)

bp = Blueprint("story", __name__)
logger = logging.getLogger(__name__)


def _redirect_after_story_image_op(sid: int):
    """ストーリー画像の削除・一括削除後の遷移先（一覧からの操作時は一覧へ）。"""
    if (request.form.get("redirect_target") or "").strip() == "story_index":
        return redirect(url_for("story.index"))
    return redirect(url_for("story.detail", sid=sid))


_MAX_PIXIV_GEMINI_RAW = 120_000


def _parse_seed_int(form_key: str = "seed") -> int:
    """
    生成・予約フォームの seed を解釈する。
    空・-1・random はランダム（-1）。それ以外は整数（大きな値も可。HTML number の桁落ち対策で text 推奨）。
    """
    raw = (request.form.get(form_key) or "").strip()
    if raw == "" or raw == "-1" or raw.lower() in ("rand", "random", "r"):
        return -1
    try:
        return int(raw, 10)
    except ValueError:
        return -1


def _apply_sd_default_seed_from_form(target: dict) -> None:
    """default_seed フォーム値を target に sd_default_seed として反映（空ならキー削除）。"""
    raw = (request.form.get("default_seed") or "").strip()
    if raw == "" or raw == "-1" or raw.lower() in ("rand", "random", "r"):
        target.pop("sd_default_seed", None)
        return
    try:
        target["sd_default_seed"] = int(raw, 10)
    except ValueError:
        pass


def _parse_variant_index_form() -> int | None:
    raw_vi = request.form.get("variant_index")
    if raw_vi is None or str(raw_vi).strip() == "":
        return None
    try:
        return int(raw_vi)
    except (TypeError, ValueError):
        return None


def _parse_overlay_include_speech() -> bool:
    """画像オーバーレイで下段のセリフ（speech）を含めるか。フォーム select: 1=含める / 0=上段ストーリーのみ。"""
    raw = (request.form.get("overlay_include_speech") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _parse_overlay_include_chapter_title() -> bool:
    """焼き増し時に上段へ章の見出し（title）を含めるか。1=含める / 0=要約（scene）のみ。"""
    raw = (request.form.get("overlay_include_chapter_title") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _parse_overlay_include_top_story() -> bool:
    """焼き増し時に上段のストーリー帯（title/scene）を載せるか。0=上段なし（セリフのみ等）。"""
    raw = (request.form.get("overlay_include_top_story") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _parse_speech_preset_index_form() -> int | None:
    """セリフプリセット番号。空=章の speech。0〜SPEECH_PRESET_SLOTS-1。"""
    raw = (request.form.get("speech_preset_index") or "").strip()
    if raw == "":
        return None
    try:
        idx = int(raw, 10)
    except (TypeError, ValueError):
        return None
    if idx < 0 or idx >= Story.SPEECH_PRESET_SLOTS:
        return None
    return idx


def _sd_form_suffix(ch_no: int, variant_index: int | None) -> str:
    v = "n" if variant_index is None else str(variant_index)
    return f"{ch_no}_{v}"


def _persist_sd_generate_session(sid: int, ch_no: int, variant_index: int | None) -> None:
    """今すぐ生成フォームの入力をセッションに保存（リダイレクト後も同じ値を表示）。"""
    key = f"sd_gen_{sid}_{_sd_form_suffix(ch_no, variant_index)}"
    session[key] = {
        "steps": (request.form.get("steps") or "").strip() or "20",
        "batch_size": (request.form.get("batch_size") or "").strip() or "1",
        "n_iter": (request.form.get("n_iter") or "").strip() or "1",
        "width": (request.form.get("width") or "").strip() or "512",
        "height": (request.form.get("height") or "").strip() or "768",
        "cfg_scale": (request.form.get("cfg_scale") or "").strip() or "7",
        "sampler_name": (request.form.get("sampler_name") or "").strip()
        or sanitize_sampler_name(None),
        "enable_hr": "1" if sanitize_enable_hr(request.form.get("enable_hr")) else "0",
        "hr_scale": (request.form.get("hr_scale") or "").strip() or "2",
        "hr_denoising_strength": (request.form.get("hr_denoising_strength") or "").strip()
        or "0.5",
        "hr_second_pass_steps": (request.form.get("hr_second_pass_steps") or "").strip() or "0",
        "hr_upscaler": (request.form.get("hr_upscaler") or "").strip(),
        "seed": (request.form.get("seed") or "").strip() or "-1",
        "overlay_include_top_story": "1" if _parse_overlay_include_top_story() else "0",
        "overlay_include_speech": "1" if _parse_overlay_include_speech() else "0",
        "speech_preset_index": (request.form.get("speech_preset_index") or "").strip(),
    }
    session.modified = True


def _persist_sd_schedule_session(sid: int, ch_no: int, variant_index: int | None) -> None:
    """日時予約フォームの入力をセッションに保存。"""
    key = f"sd_sched_{sid}_{_sd_form_suffix(ch_no, variant_index)}"
    session[key] = {
        "scheduled_at": (request.form.get("scheduled_at") or "").strip(),
        "steps": (request.form.get("steps") or "").strip() or "20",
        "batch_size": (request.form.get("batch_size") or "").strip() or "1",
        "n_iter": (request.form.get("n_iter") or "").strip() or "1",
        "width": (request.form.get("width") or "").strip() or "512",
        "height": (request.form.get("height") or "").strip() or "768",
        "cfg_scale": (request.form.get("cfg_scale") or "").strip() or "7",
        "sampler_name": (request.form.get("sampler_name") or "").strip()
        or sanitize_sampler_name(None),
        "enable_hr": "1" if sanitize_enable_hr(request.form.get("enable_hr")) else "0",
        "hr_scale": (request.form.get("hr_scale") or "").strip() or "2",
        "hr_denoising_strength": (request.form.get("hr_denoising_strength") or "").strip()
        or "0.5",
        "hr_second_pass_steps": (request.form.get("hr_second_pass_steps") or "").strip() or "0",
        "hr_upscaler": (request.form.get("hr_upscaler") or "").strip(),
        "seed": (request.form.get("seed") or "").strip() or "-1",
        "overlay_include_top_story": "1" if _parse_overlay_include_top_story() else "0",
        "overlay_include_speech": "1" if _parse_overlay_include_speech() else "0",
        "speech_preset_index": (request.form.get("speech_preset_index") or "").strip(),
    }
    session.modified = True


def _maybe_persist_generate_form(sid: int) -> None:
    ch_no = request.form.get("ch_no", type=int)
    if not ch_no or ch_no < 1:
        return
    _persist_sd_generate_session(sid, ch_no, _parse_variant_index_form())


def _maybe_persist_schedule_form(sid: int) -> None:
    ch_no = request.form.get("ch_no", type=int)
    if not ch_no or ch_no < 1:
        return
    _persist_sd_schedule_session(sid, ch_no, _parse_variant_index_form())


def _session_saved_sd_forms(sid: int) -> tuple[dict[str, dict], dict[str, dict]]:
    """ストーリー詳細でフォームに戻す保存済みパラメータ（シーン×パターンごと）。"""
    gen: dict[str, dict] = {}
    sched: dict[str, dict] = {}
    pgen = f"sd_gen_{sid}_"
    psch = f"sd_sched_{sid}_"
    for k, v in list(session.items()):
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        if k.startswith(pgen):
            gen[k[len(pgen) :]] = v
        elif k.startswith(psch):
            sched[k[len(psch) :]] = v
    return gen, sched


def _normalize_gemini_story(result: dict) -> dict:
    """章の prompt / neg を補完し、必須キーを揃える。"""
    chapters = result.get("chapters")
    if not isinstance(chapters, list):
        result["chapters"] = []
        return result
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        variants = ch.get("prompt_variants")
        if isinstance(variants, list) and variants:
            first = variants[0] if isinstance(variants[0], dict) else {}
            if not (ch.get("prompt") or "").strip():
                ch["prompt"] = (first.get("prompt") or "").strip()
            if not (ch.get("neg") or "").strip():
                ch["neg"] = (first.get("neg") or "").strip()
        ch.setdefault("prompt", "")
        ch.setdefault("neg", "")
        ch.setdefault("scene", "")
        ch.setdefault("title", "")
        ch.setdefault("notes_jp", "")
        if ch.get("no") is None:
            ch["no"] = i + 1
    return result


def _build_reference_prompt_block(
    character_id: int, prompt_ids: list[int], base_free: str, base_neg_free: str
) -> tuple[str, str]:
    """
    Gemini 用のベースプロンプト本文と、DB 保存用の短い要約を返す。
    ライブラリ ID は必ず同一キャラに属するものだけ採用する。
    """
    lines: list[str] = []
    snap_parts: list[str] = []
    for pid in prompt_ids:
        p = Prompt.query.get(pid)
        if not p or p.character_id != character_id:
            continue
        label = p.situation or "シチュ未設定"
        lines.append(f"--- プロンプトライブラリ ID#{p.id} ({label}) ---")
        if p.positive:
            lines.append(f"Positive: {p.positive}")
        if p.negative:
            lines.append(f"Negative: {p.negative}")
        if p.notes:
            lines.append(f"制作メモ: {p.notes}")
        snap_parts.append(f"#{p.id} {label}")
    if base_free:
        lines.append("--- 手入力・追記のベース（Positive・画風・方針など）---")
        lines.append(base_free)
        snap_parts.append("手入力ポジあり")
    if base_neg_free:
        lines.append(
            "--- 手入力の共通ネガティブプロンプト（全章の neg に必ず含め、ライブラリのネガと矛盾させない）---"
        )
        lines.append(base_neg_free)
        snap_parts.append("手入力ネガあり")
    block = "\n".join(lines).strip()
    snapshot = " | ".join(snap_parts)[:4000]
    return block, snapshot


def _source_character_id_for_story(story_id: int | None) -> int | None:
    """保存済みストーリー行の character_id（別キャラ改稿時の比較用）。"""
    if not story_id:
        return None
    srow = Story.query.get(story_id)
    return srow.character_id if srow else None


def _parse_chapters_form(raw: str) -> tuple[str | None, str]:
    """章 JSON 文字列を検証し、保存用 JSON 文字列を返す。"""
    if not raw.strip():
        return None, "[]"
    try:
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            return "章データは配列である必要があります", "[]"
        return None, json.dumps(parsed, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return f"章データの JSON が不正です: {e}", "[]"


@bp.route("/")
def index():
    """ストーリー一覧と生成フォーム。"""
    characters = Character.query.order_by(Character.name).all()
    stories = Story.query.order_by(Story.created_at.desc()).all()
    story_ids = [s.id for s in stories]
    images_by_story: dict[int, list[Image]] = {}
    if story_ids:
        for im in (
            Image.query.filter(Image.story_id.in_(story_ids))
            .order_by(Image.created_at.desc())
            .all()
        ):
            if im.story_id is not None:
                images_by_story.setdefault(im.story_id, []).append(im)
    # 一覧は全ストーリー分の画像が集まるため、既定ではまとめ署名しない（S3 直列が極端に重い）。
    image_view_urls: dict[int, str] = {}
    if current_app.config.get("STORY_INDEX_GALLERY_PRESIGN"):
        flat_story_images: list[Image] = []
        for lst in images_by_story.values():
            flat_story_images.extend(lst)
        cap = int(current_app.config.get("STORY_INDEX_GALLERY_PRESIGN_MAX", 48))
        if cap <= 0:
            image_view_urls = {}
        else:
            image_view_urls = s3_service.batch_presigned_portal_image_view_urls(
                flat_story_images[:cap]
            )
    library_prompts = (
        Prompt.query.order_by(Prompt.is_starred.desc(), Prompt.created_at.desc())
        .limit(500)
        .all()
    )
    today = date.today()
    default_season_month = today.month
    default_season_week = week_of_month(today)
    return render_template(
        "story/index.html",
        characters=characters,
        stories=stories,
        images_by_story=images_by_story,
        image_view_urls=image_view_urls,
        library_prompts=library_prompts,
        default_season_month=default_season_month,
        default_season_week=default_season_week,
    )


@bp.route("/generate", methods=["POST"])
def generate():
    """AI でストーリーと章別プロンプトを生成（htmx）。"""
    character_id = request.form.get("character_id", type=int)
    premise = request.form.get("premise", "").strip()
    base_free = request.form.get("base_prompt_free", "").strip()
    base_neg_free = request.form.get("base_negative_free", "").strip()
    prompt_ids = [i for i in request.form.getlist("prompt_ids", type=int) if i]
    genres = request.form.getlist("genres")
    tones = request.form.getlist("tones")
    raw_nc = request.form.get("num_chapters")
    num_chapters = int(raw_nc) if raw_nc and raw_nc.isdigit() else 5

    seasonal_on, season_m, season_w = parse_seasonal_form(
        request.form.get("seasonal_enable") == "1",
        request.form.get("season_month"),
        request.form.get("season_week"),
    )
    rotation_note = (request.form.get("seasonal_rotation_note") or "").strip()

    if not character_id:
        return '<p class="text-red-600 text-sm">キャラクターを選択してください</p>', 400
    if not premise and not base_free and not base_neg_free and not prompt_ids:
        return (
            '<p class="text-red-600 text-sm">'
            "「あらすじ・依頼内容」「手入力ベース（Positive）」「手入力ベース（Negative）」"
            "「ライブラリからの選択」の<strong>いずれか1つ以上</strong>を指定してください。"
            "</p>",
            400,
        )

    character = Character.query.get_or_404(character_id)

    logger.info(
        "story.generate: リクエスト受付 character_id=%s name=%r premise_chars=%d "
        "base_pos_chars=%d base_neg_chars=%d library_ids=%d num_chapters=%s",
        character_id,
        character.name,
        len(premise),
        len(base_free),
        len(base_neg_free),
        len(prompt_ids),
        num_chapters,
    )
    if seasonal_on:
        logger.info(
            "story.generate: 季節テンプレ month=%s week=%s rotation_note_chars=%d",
            season_m,
            season_w,
            len(rotation_note),
        )

    ref_block, basis_snapshot = _build_reference_prompt_block(
        character_id, prompt_ids, base_free, base_neg_free
    )
    premise_for_api = premise or (
        "（あらすじは省略。以下のベースプロンプトの雰囲気・タグに沿って、"
        "自然な短編として章立て・シーン・SDプロンプトを生成してください。）"
    )

    # f-string の {} 内に "\n" 等のバックスラッシュを書けない環境があるため先に組み立てる
    seasonal_addon = ""
    if seasonal_on:
        seasonal_addon = "\n\n" + build_seasonal_user_addon(
            season_m, season_w, rotation_note or None
        )

    user_message = f"""
キャラクター名: {character.name}
キャラクターの特徴: {character.tags or '（未設定）'}
使用SDモデル: {character.sd_model or '未設定'}
LoRA 名（指定時は各シーン positive 末尾に lora:名:1 を付与）: {character.lora_name or '（なし）'}
ジャンル: {', '.join(genres) or 'ファンタジー'}
トーン: {', '.join(tones) or 'ドラマチック'}

【あらすじ・依頼内容】（メインでも補助でもよい）
{premise_for_api}

章の数: {num_chapters}

【ベースプロンプト】（蓄積したポジ・ネガ等。章の SD プロンプトはこれと一貫させる）
{ref_block or "（ライブラリ・手入力とも未指定。キャラ特徴とあらすじのみから生成。）"}
{seasonal_addon}
    """.strip()

    try:
        result = call_gemini_json(
            STORY_SYSTEM_PROMPT,
            user_message,
            max_tokens=current_app.config.get(
                "GEMINI_STORY_MAX_OUTPUT_TOKENS", 65536
            ),
            log_label="story.generate",
        )
        if "chapters" not in result or not isinstance(result["chapters"], list):
            result["chapters"] = []
        result.setdefault("title", "")
        result.setdefault("overview", "")
        result.setdefault("narrative", "")
        result.setdefault("common_setting", "")
        _normalize_gemini_story(result)
        ch_count = len(result.get("chapters") or [])
        logger.info(
            "story.generate: 完了 title=%r chapters=%d narrative_chars=%d",
            (result.get("title") or "")[:80],
            ch_count,
            len(result.get("narrative") or ""),
        )
        basis_for_save = ""
        if ref_block:
            basis_for_save = f"{basis_snapshot}\n\n---\n{ref_block}"[:65000]
        elif basis_snapshot:
            basis_for_save = basis_snapshot
        if seasonal_on:
            tag = f"[季節テンプレ] {seasonal_summary_line(season_m, season_w)}"
            if rotation_note:
                tag += f" / ローテ: {rotation_note[:200]}"
            basis_for_save = (
                f"{basis_for_save}\n\n{tag}" if basis_for_save else tag
            )[:65000]

        return render_template(
            "story/result_partial.html",
            story=result,
            character=character,
            premise=premise,
            genres=",".join(genres),
            tones=",".join(tones),
            prompt_basis=basis_for_save,
            revise_hx_target="#story-result",
            story_id=None,
            source_character_id=None,
        )
    except Exception as e:
        logger.exception("story.generate: 失敗 character_id=%s", character_id)
        return f'<p class="text-red-600 text-sm">生成エラー: {e}</p>', 500


@bp.route("/save", methods=["POST"])
def save():
    """生成結果または手入力を DB に保存。"""
    character_id = request.form.get("character_id", type=int)
    title = request.form.get("title", "").strip()
    overview = request.form.get("overview", "").strip()
    narrative = (request.form.get("narrative") or "").strip() or None
    common_setting = (request.form.get("common_setting") or "").strip() or None
    chapters_json = request.form.get("chapters_json", "").strip()
    genre = request.form.get("genre", "").strip() or None
    tone = request.form.get("tone", "").strip() or None
    premise = request.form.get("premise", "").strip() or None

    if not character_id or not title:
        flash("キャラクターとタイトルは必須です。", "error")
        return redirect(url_for("story.index"))

    err, chapters_store = _parse_chapters_form(chapters_json)
    if err:
        flash(err, "error")
        return redirect(url_for("story.index"))

    prompt_basis = (request.form.get("prompt_basis") or "").strip() or None

    story = Story(
        character_id=character_id,
        title=title,
        overview=overview or None,
        narrative=narrative,
        common_setting=common_setting,
        genre=genre,
        tone=tone,
        premise=premise,
        prompt_basis=prompt_basis,
        chapters_json=chapters_store,
    )
    db.session.add(story)
    db.session.commit()
    flash("ストーリーを保存しました。", "success")
    return redirect(url_for("story.index"))


@bp.route("/revise", methods=["POST"])
def revise():
    """既存ストーリー JSON に対し、自然言語指示で加筆・修正（htmx）。"""
    instruction = (request.form.get("instruction") or "").strip()
    character_id = request.form.get("character_id", type=int)
    snapshot_raw = (request.form.get("story_snapshot") or "").strip()
    story_id = request.form.get("story_id", type=int)
    revise_hx_target = (request.form.get("revise_hx_target") or "#story-result").strip()
    if not revise_hx_target.startswith("#"):
        revise_hx_target = "#story-result"
    premise = request.form.get("premise", "").strip()
    genre = request.form.get("genre", "").strip()
    tone = request.form.get("tone", "").strip()
    prompt_basis = (request.form.get("prompt_basis") or "").strip() or None

    if not instruction:
        return '<p class="text-red-600 text-sm">編集指示を入力してください。</p>', 400
    if not character_id:
        return '<p class="text-red-600 text-sm">キャラクター ID が不正です。</p>', 400
    if not snapshot_raw:
        return '<p class="text-red-600 text-sm">作品データがありません。</p>', 400

    try:
        snapshot = json.loads(snapshot_raw)
    except json.JSONDecodeError:
        return '<p class="text-red-600 text-sm">作品データの JSON が壊れています。</p>', 400
    if not isinstance(snapshot, dict):
        return '<p class="text-red-600 text-sm">作品データは JSON オブジェクトである必要があります。</p>', 400

    character = Character.query.get_or_404(character_id)

    logger.info(
        "story.revise: 受付 character_id=%s story_id=%s instruction_chars=%d snapshot_chars=%d",
        character_id,
        story_id,
        len(instruction),
        len(snapshot_raw),
    )

    user_message = f"""
キャラクター名: {character.name}
キャラクターの特徴: {character.tags or '（未設定）'}
使用SDモデル: {character.sd_model or '未設定'}
LoRA 名: {character.lora_name or '（なし）'}

【現在の作品データ（JSON・これをベースに編集すること）】
{json.dumps(snapshot, ensure_ascii=False)}

【編集指示】
{instruction}
    """.strip()

    try:
        result = call_gemini_json(
            STORY_REVISE_SYSTEM_PROMPT,
            user_message,
            max_tokens=current_app.config.get(
                "GEMINI_STORY_MAX_OUTPUT_TOKENS", 65536
            ),
            log_label="story.revise",
        )
        if "chapters" not in result or not isinstance(result["chapters"], list):
            result["chapters"] = []
        result.setdefault("title", "")
        result.setdefault("overview", "")
        result.setdefault("narrative", "")
        result.setdefault("common_setting", "")
        _normalize_gemini_story(result)
        logger.info(
            "story.revise: 完了 chapters=%d narrative_chars=%d",
            len(result.get("chapters") or []),
            len(result.get("narrative") or ""),
        )
        return render_template(
            "story/result_partial.html",
            story=result,
            character=character,
            premise=premise,
            genres=genre,
            tones=tone,
            prompt_basis=prompt_basis,
            revise_hx_target=revise_hx_target,
            story_id=story_id,
            source_character_id=_source_character_id_for_story(story_id),
        )
    except Exception as e:
        logger.exception("story.revise: 失敗 character_id=%s", character_id)
        return f'<p class="text-red-600 text-sm">修正エラー: {e}</p>', 500


@bp.route("/recharacterize", methods=["POST"])
def recharacterize():
    """別キャラ＋ユーザー指定ベースプロンプトで、既存ストーリー JSON を全面改稿（htmx）。"""
    base_prompt = (request.form.get("base_prompt") or "").strip()
    extra = (request.form.get("recharacterize_note") or "").strip()
    character_id = request.form.get("character_id", type=int)
    snapshot_raw = (request.form.get("story_snapshot") or "").strip()
    story_id = request.form.get("story_id", type=int)
    revise_hx_target = (request.form.get("revise_hx_target") or "#story-result").strip()
    if not revise_hx_target.startswith("#"):
        revise_hx_target = "#story-result"
    premise = request.form.get("premise", "").strip()
    genre = request.form.get("genre", "").strip()
    tone = request.form.get("tone", "").strip()
    old_prompt_basis = (request.form.get("prompt_basis") or "").strip()

    if not base_prompt:
        return '<p class="text-red-600 text-sm">ベースプロンプトを入力してください。</p>', 400
    if not character_id:
        return '<p class="text-red-600 text-sm">差し替え先のキャラクターを選んでください。</p>', 400
    if not snapshot_raw:
        return '<p class="text-red-600 text-sm">作品データがありません。</p>', 400

    try:
        snapshot = json.loads(snapshot_raw)
    except json.JSONDecodeError:
        return '<p class="text-red-600 text-sm">作品データの JSON が壊れています。</p>', 400
    if not isinstance(snapshot, dict):
        return '<p class="text-red-600 text-sm">作品データは JSON オブジェクトである必要があります。</p>', 400

    new_character = Character.query.get_or_404(character_id)

    old_block = "（不明・スナップショットのみ）"
    if story_id:
        st_old = Story.query.get(story_id)
        if st_old and st_old.character:
            oc = st_old.character
            old_block = (
                f"名前: {oc.name}\n"
                f"特徴: {oc.tags or '（未設定）'}\n"
                f"SDモデル: {oc.sd_model or '未設定'}\n"
                f"LoRA: {oc.lora_name or '（なし）'}"
            )

    logger.info(
        "story.recharacterize: 受付 new_character_id=%s story_id=%s base_prompt_chars=%d snapshot_chars=%d",
        character_id,
        story_id,
        len(base_prompt),
        len(snapshot_raw),
    )

    user_message = f"""
【旧キャラ（置き換え元・テキスト・プロンプトから除去・置換すること）】
{old_block}

【差し替え先キャラ（DB。名前・タグ・モデル・LoRA を参照）】
名前: {new_character.name}
特徴: {new_character.tags or '（未設定）'}
使用SDモデル: {new_character.sd_model or '未設定'}
LoRA 名（指定時は各シーン positive 末尾に lora:名:1 を付与）: {new_character.lora_name or '（なし）'}

【ベースプロンプト（外見・衣装・SDタグの正。これを最優先で踏襲・反映すること）】
{base_prompt}

【現在の作品データ（JSON・構成のベースにし、キャラ表現だけ全面改稿）】
{json.dumps(snapshot, ensure_ascii=False)}

【補足指示（任意）】
{extra or "（なし）"}

【参考・旧ストーリー生成時のベース（あれば。新キャラ版では不要な旧キャラ要素は使わない）】
{old_prompt_basis or "（なし）"}
    """.strip()

    basis_for_save = (
        f"【再キャラクター化】差し替え先: {new_character.name} (id={new_character.id})\n\n"
        f"{base_prompt}"
    )
    if extra:
        basis_for_save += f"\n\n【補足】\n{extra}"

    try:
        result = call_gemini_json(
            STORY_RECHARACTERIZE_SYSTEM_PROMPT,
            user_message,
            max_tokens=current_app.config.get(
                "GEMINI_STORY_MAX_OUTPUT_TOKENS", 65536
            ),
            log_label="story.recharacterize",
        )
        if "chapters" not in result or not isinstance(result["chapters"], list):
            result["chapters"] = []
        result.setdefault("title", "")
        result.setdefault("overview", "")
        result.setdefault("narrative", "")
        result.setdefault("common_setting", "")
        _normalize_gemini_story(result)
        logger.info(
            "story.recharacterize: 完了 chapters=%d narrative_chars=%d",
            len(result.get("chapters") or []),
            len(result.get("narrative") or ""),
        )
        return render_template(
            "story/result_partial.html",
            story=result,
            character=new_character,
            premise=premise,
            genres=genre,
            tones=tone,
            prompt_basis=basis_for_save,
            revise_hx_target=revise_hx_target,
            story_id=story_id,
            source_character_id=_source_character_id_for_story(story_id),
        )
    except Exception as e:
        logger.exception("story.recharacterize: 失敗 character_id=%s", character_id)
        return f'<p class="text-red-600 text-sm">改稿エラー: {e}</p>', 500


@bp.route("/<int:sid>/save-as-new", methods=["POST"])
def save_as_new(sid: int):
    """プレビュー内容を新規ストーリー行として保存。元の sid は変更しない（別キャラ改稿向け）。"""
    Story.query.get_or_404(sid)
    character_id = request.form.get("character_id", type=int)
    title = request.form.get("title", "").strip()
    overview = request.form.get("overview", "").strip()
    narrative = (request.form.get("narrative") or "").strip() or None
    common_setting = (request.form.get("common_setting") or "").strip() or None
    chapters_json = request.form.get("chapters_json", "").strip()
    genre = request.form.get("genre", "").strip() or None
    tone = request.form.get("tone", "").strip() or None
    premise = request.form.get("premise", "").strip() or None
    prompt_basis = (request.form.get("prompt_basis") or "").strip() or None

    if not character_id:
        flash("キャラクター ID が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if not Character.query.get(character_id):
        flash("キャラクターが見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if not title:
        flash("タイトルは必須です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    err, chapters_store = _parse_chapters_form(chapters_json)
    if err:
        flash(err, "error")
        return redirect(url_for("story.detail", sid=sid))

    new_story = Story(
        character_id=character_id,
        title=title,
        overview=overview or None,
        narrative=narrative,
        common_setting=common_setting,
        genre=genre,
        tone=tone,
        premise=premise,
        prompt_basis=prompt_basis,
        chapters_json=chapters_store,
    )
    db.session.add(new_story)
    db.session.commit()
    flash(
        "新規ストーリーとして保存しました（元のストーリーは変更していません）。",
        "success",
    )
    return redirect(url_for("story.detail", sid=new_story.id))


@bp.route("/<int:sid>/update", methods=["POST"])
def update(sid: int):
    """保存済みストーリーを上書き更新。"""
    story = Story.query.get_or_404(sid)
    character_id = request.form.get("character_id", type=int)
    title = request.form.get("title", "").strip()
    overview = request.form.get("overview", "").strip()
    narrative = (request.form.get("narrative") or "").strip() or None
    common_setting = (request.form.get("common_setting") or "").strip() or None
    chapters_json = request.form.get("chapters_json", "").strip()
    genre = request.form.get("genre", "").strip() or None
    tone = request.form.get("tone", "").strip() or None
    premise = request.form.get("premise", "").strip() or None
    prompt_basis = (request.form.get("prompt_basis") or "").strip() or None

    if not character_id:
        flash("キャラクター ID が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if not Character.query.get(character_id):
        flash("キャラクターが見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if character_id != story.character_id:
        flash(
            "プレビューのキャラクターが、このストーリーに登録されているキャラと異なります。"
            "別キャラ版は「新規ストーリーとして保存」を使うと、元ストーリーを残したまま別行に保存できます。",
            "error",
        )
        return redirect(url_for("story.detail", sid=sid))
    if not title:
        flash("タイトルは必須です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    err, chapters_store = _parse_chapters_form(chapters_json)
    if err:
        flash(err, "error")
        return redirect(url_for("story.detail", sid=sid))

    story.title = title
    story.overview = overview or None
    story.narrative = narrative
    story.common_setting = common_setting
    story.genre = genre
    story.tone = tone
    story.premise = premise
    story.prompt_basis = prompt_basis
    story.chapters_json = chapters_store
    db.session.commit()
    flash("ストーリーを更新しました。", "success")
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/pixiv-from-gemini", methods=["POST"])
def pixiv_from_gemini(sid: int):
    """
    Gemini 等の Markdown 回答を Pixiv 貼り付け向けに整形し、
    「タイトル／キャプション／タグ」節があれば分割して JSON で返す。
    """
    Story.query.get_or_404(sid)
    raw = (request.form.get("raw") or "").strip()
    if not raw and request.is_json and request.json:
        raw = (request.json.get("raw") or "").strip()
    if not raw:
        return jsonify({"ok": False, "message": "テキストがありません。"}), 400
    if len(raw) > _MAX_PIXIV_GEMINI_RAW:
        return jsonify({"ok": False, "message": "テキストが長すぎます。"}), 400

    sections = split_gemini_pixiv_sections(raw)
    titles_s = sanitize_markdown_for_pixiv(sections["titles"])
    caption_s = sanitize_markdown_for_pixiv(sections["caption"])
    tags_s = tags_block_to_pixiv_lines(sections["tags"])
    full_s = sanitize_markdown_for_pixiv(raw)

    suggested = first_japanese_title_candidate(sections["titles"]) or first_japanese_title_candidate(
        raw
    )

    return jsonify(
        {
            "ok": True,
            "full_sanitized": full_s,
            "titles_sanitized": titles_s,
            "caption_sanitized": caption_s,
            "tags_sanitized": tags_s,
            "suggested_title": suggested,
        }
    )


@bp.route("/<int:sid>/pixiv-post/save", methods=["POST"])
def save_pixiv_post(sid: int):
    """Pixiv 向けタイトル・キャプション・タグをストーリーに紐づけて保存。"""
    story = Story.query.get_or_404(sid)
    title = (request.form.get("pixiv_post_title") or "").strip() or None
    if title and len(title) > 500:
        title = title[:500]
    caption = (request.form.get("pixiv_post_caption") or "").strip() or None
    tags = (request.form.get("pixiv_post_tags") or "").strip() or None

    story.pixiv_post_title = title
    story.pixiv_post_caption = caption
    story.pixiv_post_tags = tags
    db.session.commit()
    flash("Pixiv 投稿文案を保存しました。", "success")
    return redirect(url_for("story.detail", sid=sid))


def _sync_main_prompt_from_first_variant(ch: dict) -> None:
    """prompt_variants があるとき、先頭パターンを章の prompt / neg に写す（生成 API と整合）。"""
    variants = ch.get("prompt_variants")
    if not isinstance(variants, list) or not variants:
        return
    v0 = variants[0]
    if isinstance(v0, dict):
        ch["prompt"] = (v0.get("prompt") or "").strip()
        ch["neg"] = (v0.get("neg") or "").strip()


def _set_optional_speech(target: dict, speech: str) -> None:
    """chapters_json 用。空ならキーを削除して JSON をすっきりさせる。"""
    if speech:
        target["speech"] = speech
    else:
        target.pop("speech", None)


@bp.route("/<int:sid>/chapters/update-prompts", methods=["POST"])
def update_chapter_prompts(sid: int):
    """シーン単位で Positive / Negative（とパターン名・任意のセリフ）を編集して保存。"""
    story = Story.query.get_or_404(sid)
    ch_no = request.form.get("ch_no", type=int)
    if not ch_no or ch_no < 1:
        flash("シーン番号が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    raw_vi = (request.form.get("variant_index") or "").strip()
    if raw_vi == "":
        variant_index: int | None = None
    else:
        try:
            variant_index = int(raw_vi)
        except ValueError:
            flash("パターン番号が不正です。", "error")
            return redirect(url_for("story.detail", sid=sid))

    pos = (request.form.get("prompt") or "").strip()
    neg = (request.form.get("neg") or "").strip()
    label = (request.form.get("variant_label") or "").strip()
    speech = (request.form.get("speech") or "").strip()

    chapters = story.get_chapters()
    found = False
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        no = ch.get("no")
        try:
            n = int(no) if no is not None else i + 1
        except (TypeError, ValueError):
            n = i + 1
        if n != ch_no:
            continue
        found = True
        variants = ch.get("prompt_variants")
        has_variants = isinstance(variants, list) and len(variants) > 0
        if has_variants and variant_index is not None:
            if variant_index < 0 or variant_index >= len(variants):
                flash("パターン番号が範囲外です。", "error")
                return redirect(url_for("story.detail", sid=sid))
            v = variants[variant_index]
            if not isinstance(v, dict):
                v = {}
                variants[variant_index] = v
            v["prompt"] = pos
            v["neg"] = neg
            if label:
                v["label"] = label
            _set_optional_speech(v, speech)
            _apply_sd_default_seed_from_form(v)
            _sync_main_prompt_from_first_variant(ch)
        else:
            ch["prompt"] = pos
            ch["neg"] = neg
            _set_optional_speech(ch, speech)
            _apply_sd_default_seed_from_form(ch)
        break

    if not found:
        flash(f"シーン番号 {ch_no} が見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))

    story.set_chapters(chapters)
    db.session.commit()
    flash(
        f"シーン {ch_no} のプロンプトを保存しました（任意のセリフ・デフォルト seed を指定していればそれらも保存済み）。",
        "success",
    )
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/chapters/update", methods=["POST"])
def update_chapters(sid: int):
    """章 JSON のみ更新（SD で調整したプロンプトを手動で反映する用）。"""
    story = Story.query.get_or_404(sid)
    raw = (request.form.get("chapters_json") or "").strip()
    err, chapters_store = _parse_chapters_form(raw)
    if err:
        flash(err, "error")
        return redirect(url_for("story.detail", sid=sid))
    story.chapters_json = chapters_store
    db.session.commit()
    flash("章データ（シーン・プロンプト）を更新しました。", "success")
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/chapters/append-variant", methods=["POST"])
def append_chapter_variant(sid: int):
    """指定シーンに prompt_variants を 1 件追加（JSON を開かずに追記する用）。"""
    story = Story.query.get_or_404(sid)
    ch_no = request.form.get("ch_no", type=int)
    label = (request.form.get("variant_label") or "").strip() or "SD で調整したパターン"
    prompt = (request.form.get("variant_prompt") or "").strip()
    neg = (request.form.get("variant_neg") or "").strip()
    variant_speech = (request.form.get("variant_speech") or "").strip()
    raw_seed = (request.form.get("variant_default_seed") or "").strip()
    extra_seed = {}
    if raw_seed and raw_seed not in ("-1",) and raw_seed.lower() not in ("rand", "random", "r"):
        try:
            extra_seed["sd_default_seed"] = int(raw_seed, 10)
        except ValueError:
            pass
    if not ch_no or not prompt:
        flash("シーン番号と Positive（プロンプト）は必須です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    chapters = story.get_chapters()
    found = False
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        no = ch.get("no")
        try:
            n = int(no) if no is not None else i + 1
        except (TypeError, ValueError):
            n = i + 1
        if n != ch_no:
            continue
        found = True
        variants = ch.get("prompt_variants")
        if not isinstance(variants, list):
            variants = []
        if len(variants) == 0 and (ch.get("prompt") or ch.get("neg")):
            v0: dict = {
                "label": "既定",
                "prompt": (ch.get("prompt") or "").strip(),
                "neg": (ch.get("neg") or "").strip(),
            }
            main_sp = (ch.get("speech") or "").strip()
            if main_sp:
                v0["speech"] = main_sp
            variants = [v0]
        new_v: dict = {"label": label, "prompt": prompt, "neg": neg}
        new_v.update(extra_seed)
        _set_optional_speech(new_v, variant_speech)
        variants.append(new_v)
        ch["prompt_variants"] = variants
        break

    if not found:
        flash(f"シーン番号 {ch_no} が見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))

    story.set_chapters(chapters)
    db.session.commit()
    flash(f"シーン {ch_no} にプロンプトパターンを追加しました。", "success")
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/schedule-chapter-image", methods=["POST"])
def schedule_chapter_image(sid: int):
    """指定日時に章画像生成を実行するよう DB に予約する。"""
    story = Story.query.get_or_404(sid)
    character = story.character or Character.query.get_or_404(story.character_id)
    ch_no = request.form.get("ch_no", type=int)
    variant_index = _parse_variant_index_form()
    steps = request.form.get("steps", type=int) or 20
    width = request.form.get("width", type=int) or 512
    height = request.form.get("height", type=int) or 768
    seed = _parse_seed_int("seed")

    try:
        batch_size, n_iter = normalize_batch_n_iter(
            request.form.get("batch_size", type=int),
            request.form.get("n_iter", type=int),
        )
    except ValueError as e:
        flash(str(e), "error")
        _maybe_persist_schedule_form(sid)
        return redirect(url_for("story.detail", sid=sid))

    cfg_scale = sanitize_cfg_scale(request.form.get("cfg_scale"))
    sampler_name = sanitize_sampler_name(request.form.get("sampler_name"))
    enable_hr = sanitize_enable_hr(request.form.get("enable_hr"))
    hr_scale = sanitize_hr_scale(request.form.get("hr_scale"))
    hr_denoising_strength = sanitize_hr_denoising_strength(
        request.form.get("hr_denoising_strength")
    )
    hr_second_pass_steps = sanitize_hr_second_pass_steps(
        request.form.get("hr_second_pass_steps")
    )
    hr_upscaler = sanitize_hr_upscaler(request.form.get("hr_upscaler"))

    scheduled_at = parse_scheduled_at_to_utc_naive(
        request.form.get("scheduled_at") or "",
        current_app.config.get("SD_SCHEDULER_TIMEZONE"),
    )
    if not ch_no or ch_no < 1:
        flash("シーン番号が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if scheduled_at is None:
        flash("実行予定日時を入力してください。", "error")
        _maybe_persist_schedule_form(sid)
        return redirect(url_for("story.detail", sid=sid))

    job = ScheduledImageJob(
        story_id=story.id,
        character_id=character.id,
        ch_no=ch_no,
        variant_index=variant_index,
        steps=steps,
        width=width,
        height=height,
        batch_size=batch_size,
        n_iter=n_iter,
        cfg_scale=cfg_scale,
        sampler_name=sampler_name,
        enable_hr=enable_hr,
        hr_scale=hr_scale,
        hr_denoising_strength=hr_denoising_strength,
        hr_second_pass_steps=hr_second_pass_steps,
        hr_upscaler=hr_upscaler,
        seed=(seed if seed >= 0 else None),
        overlay_include_top_story=_parse_overlay_include_top_story(),
        overlay_include_speech=_parse_overlay_include_speech(),
        speech_preset_index=_parse_speech_preset_index_form(),
        scheduled_at=scheduled_at,
        status=ScheduledImageJob.STATUS_PENDING,
    )
    db.session.add(job)
    db.session.commit()
    msg = (
        f"シーン {ch_no} の生成を {scheduled_at.strftime('%Y-%m-%d %H:%M')} UTC に予約しました"
        f"（入力は {current_app.config.get('SD_SCHEDULER_TIMEZONE') or 'Asia/Tokyo'} として解釈）。"
    )
    if not current_app.config.get("SD_SCHEDULER_ENABLED"):
        msg += " 自動実行には .env で SD_SCHEDULER_ENABLED=1 を有効にし、ポータルを常時起動してください。"
    flash(msg, "success")
    _maybe_persist_schedule_form(sid)
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/schedule/<int:jid>/cancel", methods=["POST"])
def cancel_scheduled_job(sid: int, jid: int):
    """予約中（pending）のジョブのみ取り消し。"""
    job = ScheduledImageJob.query.get_or_404(jid)
    if job.story_id != sid:
        flash("予約が見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))
    if job.status != ScheduledImageJob.STATUS_PENDING:
        flash("取り消せるのは「予定中」のジョブのみです。", "error")
        return redirect(url_for("story.detail", sid=sid))
    job.status = ScheduledImageJob.STATUS_CANCELLED
    job.completed_at = datetime.utcnow()
    db.session.commit()
    flash("予約を取り消しました。", "success")
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>/speech-presets", methods=["POST"])
def update_speech_presets(sid: int):
    """ストーリー単位のセリフプリセット10枠を保存する。"""
    story = Story.query.get_or_404(sid)
    lines: list[str] = []
    for i in range(Story.SPEECH_PRESET_SLOTS):
        lines.append(request.form.get(f"preset_{i}") or "")
    story.set_speech_presets(lines)
    db.session.commit()
    flash("セリフプリセット（10枠）を保存しました。", "success")
    return redirect(f"{url_for('story.detail', sid=sid)}#speech-presets")


@bp.route("/<int:sid>/chapter-speech-presets", methods=["POST"])
def update_chapter_speech_presets(sid: int):
    """シーン単位のセリフプリセット10枠を chapters_json に保存する。"""
    story = Story.query.get_or_404(sid)
    ch_no = request.form.get("ch_no", type=int)
    if not ch_no or ch_no < 1:
        flash("シーン番号が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    lines = [request.form.get(f"preset_{i}") or "" for i in range(Story.SPEECH_PRESET_SLOTS)]
    chapters = story.get_chapters()
    found = False
    for i, ch in enumerate(chapters):
        if not isinstance(ch, dict):
            continue
        no = ch.get("no")
        try:
            n = int(no) if no is not None else i + 1
        except (TypeError, ValueError):
            n = i + 1
        if n != ch_no:
            continue
        found = True
        set_chapter_speech_presets(ch, lines)
        break

    if not found:
        flash(f"シーン番号 {ch_no} が見つかりません。", "error")
        return redirect(url_for("story.detail", sid=sid))

    story.set_chapters(chapters)
    db.session.commit()
    flash(f"シーン {ch_no} のセリフプリセット（10枠）を保存しました。", "success")
    return redirect(f"{url_for('story.detail', sid=sid)}#chapter-{ch_no}-speech-presets")


@bp.route("/<int:sid>/images/<int:iid>/text-overlay", methods=["POST"])
def create_story_image_text_overlay(sid: int, iid: int):
    """既存画像を元に章テキストを焼き込んだ別ファイルを S3 に追加し、新しい Image 行を作る。"""
    story = Story.query.get_or_404(sid)
    img = Image.query.get_or_404(iid)
    if img.story_id != sid:
        flash("このストーリーに紐づいていない画像です。", "error")
        return _redirect_after_story_image_op(sid)
    ch_no = request.form.get("ch_no", type=int)
    raw_vi = (request.form.get("variant_index") or "").strip()
    if raw_vi == "":
        variant_index: int | None = None
    else:
        try:
            variant_index = int(raw_vi)
        except ValueError:
            variant_index = None
    try:
        g_ch, _ = guess_chapter_variant_from_story_filename(img.file_name or "")
        eff_ch = ch_no if ch_no is not None and ch_no >= 1 else g_ch
        ch_dict = story.find_chapter_by_no(eff_ch) if eff_ch else None
        preset_idx = _parse_speech_preset_index_form()
        speech_override = resolve_speech_bottom_override(story, ch_dict, preset_idx)
        new_im = create_text_overlay_copy_for_story_image(
            story=story,
            source=img,
            ch_no=ch_no,
            variant_index=variant_index,
            overlay_include_speech=_parse_overlay_include_speech(),
            include_chapter_title=_parse_overlay_include_chapter_title(),
            overlay_include_top_story=_parse_overlay_include_top_story(),
            speech_bottom_override=speech_override,
        )
        flash(
            f"テキスト焼き増し版を追加しました（新規画像 ID {new_im.id}）。元画像はそのままです。",
            "success",
        )
    except ValueError as e:
        flash(str(e), "error")
    except Exception:
        logger.exception("create_story_image_text_overlay: story=%s image=%s", sid, iid)
        flash("処理中にエラーが発生しました。ログを確認してください。", "error")
    return _redirect_after_story_image_op(sid)


@bp.route("/<int:sid>/images/<int:iid>/delete", methods=["POST"])
def delete_story_image(sid: int, iid: int):
    """ストーリー画面から 1 件の Image を削除（S3 キーがあればオブジェクトも削除）。"""
    from app.routes.image import delete_portal_image

    Story.query.get_or_404(sid)
    img = Image.query.get_or_404(iid)
    if img.story_id != sid:
        flash("このストーリーに紐づいていない画像です。", "error")
        return _redirect_after_story_image_op(sid)
    ok, err = delete_portal_image(img)
    if not ok:
        flash(
            f"S3 の削除に失敗しました（DB レコードは削除しませんでした）: {err}",
            "error",
        )
        return _redirect_after_story_image_op(sid)
    flash("画像を削除しました（S3 のオブジェクトも削除済みです）。", "success")
    return _redirect_after_story_image_op(sid)


_MAX_BULK_STORY_IMAGE_DELETE = 80


@bp.route("/<int:sid>/images/bulk-delete", methods=["POST"])
def bulk_delete_story_images(sid: int):
    """ストーリーに紐づく画像を複数選択して一括削除。"""
    from app.routes.image import delete_portal_image

    Story.query.get_or_404(sid)
    raw = request.form.getlist("image_ids")
    ids: list[int] = []
    for x in raw:
        try:
            ids.append(int(x))
        except (TypeError, ValueError):
            continue
    ids = list(dict.fromkeys(ids))[:_MAX_BULK_STORY_IMAGE_DELETE]
    if not ids:
        flash("削除する画像を選択してください。", "warning")
        return _redirect_after_story_image_op(sid)

    deleted = 0
    failed: list[str] = []
    for iid in ids:
        img = Image.query.get(iid)
        if not img:
            failed.append(f"ID{iid}: 見つかりません")
            continue
        if img.story_id != sid:
            failed.append(f"ID{iid}: このストーリーに属しません")
            continue
        ok, err = delete_portal_image(img)
        if ok:
            deleted += 1
        else:
            failed.append(f"ID{iid}: {err}")

    if deleted:
        flash(
            f"{deleted} 件の画像を削除しました（S3 オブジェクトも削除済みのものがあります）。",
            "success",
        )
    if failed:
        tail = "; ".join(failed[:12])
        if len(failed) > 12:
            tail += " …"
        flash(f"削除できなかった項目: {tail}", "error" if deleted == 0 else "warning")
    return _redirect_after_story_image_op(sid)


@bp.route("/<int:sid>/generate-chapter-image", methods=["POST"])
def generate_chapter_image(sid: int):
    """章のプロンプトで Web UI API 生成 → S3 original + stripped → Image 2 行。"""
    story = Story.query.get_or_404(sid)
    character = story.character or Character.query.get_or_404(story.character_id)
    ch_no = request.form.get("ch_no", type=int)
    variant_index = _parse_variant_index_form()
    steps = request.form.get("steps", type=int) or 20
    width = request.form.get("width", type=int) or 512
    height = request.form.get("height", type=int) or 768
    seed = _parse_seed_int("seed")

    if not ch_no or ch_no < 1:
        flash("シーン番号が不正です。", "error")
        return redirect(url_for("story.detail", sid=sid))

    try:
        batch_size, n_iter = normalize_batch_n_iter(
            request.form.get("batch_size", type=int),
            request.form.get("n_iter", type=int),
        )
    except ValueError as e:
        flash(str(e), "error")
        _maybe_persist_generate_form(sid)
        return redirect(url_for("story.detail", sid=sid))

    cfg_scale = sanitize_cfg_scale(request.form.get("cfg_scale"))
    sampler_name = sanitize_sampler_name(request.form.get("sampler_name"))
    enable_hr = sanitize_enable_hr(request.form.get("enable_hr"))
    hr_scale = sanitize_hr_scale(request.form.get("hr_scale"))
    hr_denoising_strength = sanitize_hr_denoising_strength(
        request.form.get("hr_denoising_strength")
    )
    hr_second_pass_steps = sanitize_hr_second_pass_steps(
        request.form.get("hr_second_pass_steps")
    )
    hr_upscaler = sanitize_hr_upscaler(request.form.get("hr_upscaler"))

    base_url = (current_app.config.get("SD_WEBUI_BASE_URL") or "").strip()
    if not base_url:
        flash(
            "SD_WEBUI_BASE_URL が未設定です。.env に Web UI のベース URL（例: http://IP:7860）を設定してください。",
            "error",
        )
        _maybe_persist_generate_form(sid)
        return redirect(url_for("story.detail", sid=sid))
    if not s3_service.is_s3_configured():
        flash("S3 が未設定のためアップロードできません。", "error")
        _maybe_persist_generate_form(sid)
        return redirect(url_for("story.detail", sid=sid))

    try:
        ch_dict = story.find_chapter_by_no(ch_no)
        preset_idx = _parse_speech_preset_index_form()
        speech_override = resolve_speech_bottom_override(story, ch_dict, preset_idx)
        pairs = generate_chapter_images(
            story,
            character,
            ch_no,
            variant_index,
            steps=steps,
            width=width,
            height=height,
            seed=seed,
            batch_size=batch_size,
            n_iter=n_iter,
            cfg_scale=cfg_scale,
            sampler_name=sampler_name,
            enable_hr=enable_hr,
            hr_scale=hr_scale,
            hr_denoising_strength=hr_denoising_strength,
            hr_second_pass_steps=hr_second_pass_steps,
            hr_upscaler=hr_upscaler,
            overlay_include_top_story=_parse_overlay_include_top_story(),
            overlay_include_speech=_parse_overlay_include_speech(),
            speech_bottom_override=speech_override,
        )
        nimg = len(pairs)
        hr_note = "（Hi-res fix あり）" if enable_hr else ""
        flash(
            f"シーン {ch_no} を Web UI で {nimg} 枚生成し、"
            f"原本+配布用で計 {nimg * 2} 件を S3 に保存しました（batch={batch_size}×繰り返し={n_iter}）{hr_note}。",
            "success",
        )
    except ValueError as e:
        flash(str(e), "error")
    except RuntimeError as e:
        flash(str(e), "error")
    except Exception:
        logger.exception("generate_chapter_image: 失敗 story_id=%s ch_no=%s", sid, ch_no)
        flash("生成またはアップロード中にエラーが発生しました。ログを確認してください。", "error")
    _maybe_persist_generate_form(sid)
    return redirect(url_for("story.detail", sid=sid))


@bp.route("/<int:sid>")
def detail(sid: int):
    """ストーリー詳細（章一覧・コピー用）。"""
    story = Story.query.get_or_404(sid)
    chapters = story.get_chapters()
    chapters_json_pretty = json.dumps(chapters, ensure_ascii=False, indent=2)
    story_images = (
        Image.query.filter_by(story_id=sid)
        .order_by(Image.created_at.desc())
        .all()
    )
    all_characters = Character.query.order_by(Character.name.asc()).all()
    sd_generation_ready = bool(
        (current_app.config.get("SD_WEBUI_BASE_URL") or "").strip()
    ) and s3_service.is_s3_configured()
    scheduled_jobs = (
        ScheduledImageJob.query.filter_by(story_id=sid)
        .order_by(ScheduledImageJob.scheduled_at.desc())
        .limit(80)
        .all()
    )
    sd_scheduler_enabled = bool(current_app.config.get("SD_SCHEDULER_ENABLED"))
    saved_sd_gen, saved_sd_sched = _session_saved_sd_forms(sid)
    cap = int(current_app.config.get("STORY_DETAIL_GALLERY_PRESIGN_MAX", 72))
    if cap <= 0:
        to_presign: list[Image] = []
    else:
        to_presign = story_images[:cap]
    image_view_urls = (
        s3_service.batch_presigned_portal_image_view_urls(to_presign)
        if to_presign
        else {}
    )
    return render_template(
        "story/detail.html",
        story=story,
        chapters=chapters,
        chapters_json_pretty=chapters_json_pretty,
        story_images=story_images,
        image_view_urls=image_view_urls,
        all_characters=all_characters,
        sd_generation_ready=sd_generation_ready,
        scheduled_jobs=scheduled_jobs,
        sd_scheduler_enabled=sd_scheduler_enabled,
        saved_sd_gen=saved_sd_gen,
        saved_sd_sched=saved_sd_sched,
    )


@bp.route("/<int:sid>/delete", methods=["POST"])
def delete(sid: int):
    """ストーリー削除。"""
    story = Story.query.get_or_404(sid)
    Image.query.filter_by(story_id=sid).update(
        {"story_id": None}, synchronize_session=False
    )
    db.session.delete(story)
    db.session.commit()
    flash("ストーリーを削除しました。", "success")
    return redirect(url_for("story.index"))
