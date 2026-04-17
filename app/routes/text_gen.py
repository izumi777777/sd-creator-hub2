"""Pixiv / DLsite / PictSpace 向けテキスト生成。"""

import logging

from flask import Blueprint, render_template, request

from app.models.character import Character
from app.models.work import Work
from app.prompts.text_gen_prompt import DLSITE_PROMPT, PICTSPACE_PROMPT, PIXIV_PROMPT
from app.services.gemini_service import call_gemini_json

bp = Blueprint("text_gen", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    """テキスト生成フォーム。"""
    characters = Character.query.order_by(Character.name).all()
    works = Work.query.order_by(Work.created_at.desc()).all()
    return render_template(
        "text_gen/index.html",
        characters=characters,
        works=works,
    )


@bp.route("/generate", methods=["POST"])
def generate():
    """プラットフォーム別テキスト生成（htmx）。"""
    platform = request.form.get("platform", "pixiv")
    character_id = request.form.get("character_id", type=int)
    overview = request.form.get("overview", "").strip()

    if not overview:
        return '<p class="text-red-600 text-sm">作品の概要を入力してください</p>', 400
    if not character_id:
        return '<p class="text-red-600 text-sm">キャラクターを選択してください</p>', 400

    character = Character.query.get_or_404(character_id)

    prompts_map = {
        "pixiv": PIXIV_PROMPT,
        "dlsite": DLSITE_PROMPT,
        "pictspace": PICTSPACE_PROMPT,
    }
    system_prompt = prompts_map.get(platform, PIXIV_PROMPT)

    user_message = f"""
キャラクター名: {character.name}
キャラクターの特徴: {character.tags or '（未設定）'}
作品の概要: {overview}
    """.strip()

    logger.info(
        "text_gen.generate: 受付 platform=%s character_id=%s overview_chars=%d",
        platform,
        character_id,
        len(overview),
    )

    try:
        result = call_gemini_json(
            system_prompt,
            user_message,
            max_tokens=1500,
            log_label="text_gen.generate",
        )
        for key, default in (
            ("title", ""),
            ("caption", ""),
            ("tags", []),
            ("genre", ""),
            ("overview", ""),
            ("description", ""),
            ("age_rating", ""),
        ):
            result.setdefault(key, default)
        logger.info(
            "text_gen.generate: 完了 platform=%s title=%r",
            platform,
            (result.get("title") or "")[:80],
        )
        return render_template(
            "text_gen/result_partial.html",
            result=result,
            platform=platform,
        )
    except Exception as e:
        logger.exception("text_gen.generate: 失敗 platform=%s", platform)
        return f'<p class="text-red-600 text-sm">生成エラー: {e}</p>', 500
