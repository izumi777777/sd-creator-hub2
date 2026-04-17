"""プロンプトライブラリ（手動登録 + AI 生成）。"""

import logging

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
from app.models.character import Character
from app.models.prompt import Prompt
from app.prompts.sd_prompt import SD_PROMPT_SYSTEM
from app.services.gemini_service import call_gemini_json

bp = Blueprint("prompt", __name__)
logger = logging.getLogger(__name__)


@bp.route("/")
def index():
    """プロンプト一覧。"""
    character_id = request.args.get("character_id", type=int)
    q = Prompt.query
    if character_id:
        q = q.filter_by(character_id=character_id)
    prompts = q.order_by(Prompt.is_starred.desc(), Prompt.created_at.desc()).all()
    characters = Character.query.order_by(Character.name).all()
    return render_template(
        "prompt/index.html",
        prompts=prompts,
        characters=characters,
        filter_character_id=character_id,
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    """手動でプロンプト新規。"""
    characters = Character.query.order_by(Character.name).all()
    if request.method == "POST":
        cid = request.form.get("character_id", type=int)
        if not cid:
            flash("キャラクターを選択してください。", "error")
            return render_template("prompt/form.html", prompt=None, characters=characters)

        p = Prompt(
            character_id=cid,
            situation=request.form.get("situation", "").strip() or None,
            positive=request.form.get("positive", "").strip() or None,
            negative=request.form.get("negative", "").strip() or None,
            model=request.form.get("model", "").strip() or None,
            notes=request.form.get("notes", "").strip() or None,
            story_chapter_id=request.form.get("story_chapter_id", type=int),
        )
        db.session.add(p)
        db.session.commit()
        flash("プロンプトを保存しました。", "success")
        return redirect(url_for("prompt.index"))

    return render_template("prompt/form.html", prompt=None, characters=characters)


@bp.route("/<int:pid>/edit", methods=["GET", "POST"])
def edit(pid: int):
    """プロンプト編集。"""
    prompt = Prompt.query.get_or_404(pid)
    characters = Character.query.order_by(Character.name).all()
    if request.method == "POST":
        cid = request.form.get("character_id", type=int)
        if not cid:
            flash("キャラクターを選択してください。", "error")
            return render_template(
                "prompt/form.html", prompt=prompt, characters=characters
            )

        prompt.character_id = cid
        prompt.situation = request.form.get("situation", "").strip() or None
        prompt.positive = request.form.get("positive", "").strip() or None
        prompt.negative = request.form.get("negative", "").strip() or None
        prompt.model = request.form.get("model", "").strip() or None
        prompt.notes = request.form.get("notes", "").strip() or None
        prompt.story_chapter_id = request.form.get("story_chapter_id", type=int)
        db.session.commit()
        flash("プロンプトを更新しました。", "success")
        return redirect(url_for("prompt.index"))

    return render_template("prompt/form.html", prompt=prompt, characters=characters)


@bp.route("/<int:pid>/delete", methods=["POST"])
def delete(pid: int):
    """プロンプト削除。"""
    prompt = Prompt.query.get_or_404(pid)
    db.session.delete(prompt)
    db.session.commit()
    flash("プロンプトを削除しました。", "success")
    return redirect(url_for("prompt.index"))


@bp.route("/<int:pid>/star", methods=["POST"])
def star(pid: int):
    """お気に入りトグル。"""
    prompt = Prompt.query.get_or_404(pid)
    prompt.is_starred = not prompt.is_starred
    db.session.commit()
    flash("お気に入りを更新しました。", "success")
    return redirect(url_for("prompt.index"))


@bp.route("/generate", methods=["POST"])
def generate():
    """シチュエーション説明から SD プロンプトを AI 生成（htmx）。"""
    character_id = request.form.get("character_id", type=int)
    situation = request.form.get("situation", "").strip()

    if not character_id:
        return '<p class="text-red-600 text-sm">キャラクターを選択してください</p>', 400
    if not situation:
        return '<p class="text-red-600 text-sm">シチュエーションを入力してください</p>', 400

    character = Character.query.get_or_404(character_id)
    user_message = f"""
キャラクター名: {character.name}
タグ・特徴: {character.tags or '（未設定）'}
使用モデル: {character.sd_model or '未設定'}
シチュエーション説明（日本語）: {situation}
    """.strip()

    logger.info(
        "prompt.generate: 受付 character_id=%s situation_chars=%d",
        character_id,
        len(situation),
    )

    try:
        result = call_gemini_json(
            SD_PROMPT_SYSTEM,
            user_message,
            max_tokens=1200,
            log_label="prompt.generate",
        )
        result.setdefault("positive", "")
        result.setdefault("negative", "")
        result.setdefault("situation_short", "")
        logger.info(
            "prompt.generate: 完了 character_id=%s pos_chars=%d neg_chars=%d",
            character_id,
            len(result.get("positive") or ""),
            len(result.get("negative") or ""),
        )
        return render_template(
            "prompt/generate_partial.html",
            result=result,
            character=character,
            situation=situation,
        )
    except Exception as e:
        logger.exception("prompt.generate: 失敗 character_id=%s", character_id)
        return f'<p class="text-red-600 text-sm">生成エラー: {e}</p>', 500


@bp.route("/save_generated", methods=["POST"])
def save_generated():
    """AI 生成結果をライブラリに保存。"""
    cid = request.form.get("character_id", type=int)
    if not cid:
        flash("キャラクターが不正です。", "error")
        return redirect(url_for("prompt.index"))

    p = Prompt(
        character_id=cid,
        situation=request.form.get("situation", "").strip() or None,
        positive=request.form.get("positive", "").strip() or None,
        negative=request.form.get("negative", "").strip() or None,
        model=request.form.get("model", "").strip() or None,
        notes=request.form.get("notes", "").strip() or None,
    )
    db.session.add(p)
    db.session.commit()
    flash("生成プロンプトをライブラリに保存しました。", "success")
    return redirect(url_for("prompt.index"))
