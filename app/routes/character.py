"""キャラクター CRUD。"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
from app.models.character import Character

bp = Blueprint("character", __name__)


@bp.route("/")
def index():
    """キャラクター一覧。"""
    characters = Character.query.order_by(Character.created_at.desc()).all()
    return render_template("character/index.html", characters=characters)


@bp.route("/new", methods=["GET", "POST"])
def new():
    """キャラクター新規。"""
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("名前を入力してください。", "error")
            return render_template("character/form.html", character=None)

        c = Character(
            name=name,
            tags=request.form.get("tags", "").strip() or None,
            sd_model=request.form.get("sd_model", "").strip() or None,
            lora_name=request.form.get("lora_name", "").strip() or None,
            lora_weight=float(request.form.get("lora_weight") or 0.8),
            emoji=request.form.get("emoji", "🎨").strip() or "🎨",
            color=request.form.get("color", "purple").strip() or "purple",
            notes=request.form.get("notes", "").strip() or None,
        )
        db.session.add(c)
        db.session.commit()
        flash("キャラクターを登録しました。", "success")
        return redirect(url_for("character.index"))

    return render_template("character/form.html", character=None)


@bp.route("/<int:cid>/edit", methods=["GET", "POST"])
def edit(cid: int):
    """キャラクター編集。"""
    character = Character.query.get_or_404(cid)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("名前を入力してください。", "error")
            return render_template("character/form.html", character=character)

        character.name = name
        character.tags = request.form.get("tags", "").strip() or None
        character.sd_model = request.form.get("sd_model", "").strip() or None
        character.lora_name = request.form.get("lora_name", "").strip() or None
        character.lora_weight = float(request.form.get("lora_weight") or 0.8)
        character.emoji = request.form.get("emoji", "🎨").strip() or "🎨"
        character.color = request.form.get("color", "purple").strip() or "purple"
        character.notes = request.form.get("notes", "").strip() or None
        db.session.commit()
        flash("キャラクターを更新しました。", "success")
        return redirect(url_for("character.index"))

    return render_template("character/form.html", character=character)


@bp.route("/<int:cid>/delete", methods=["POST"])
def delete(cid: int):
    """キャラクター削除。"""
    character = Character.query.get_or_404(cid)
    db.session.delete(character)
    db.session.commit()
    flash("キャラクターを削除しました。", "success")
    return redirect(url_for("character.index"))
