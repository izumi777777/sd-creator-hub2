"""作品 CRUD。"""

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
from app.models.character import Character
from app.models.story import Story
from app.models.work import Work

bp = Blueprint("work", __name__)


@bp.route("/")
def index():
    """作品一覧。"""
    works = Work.query.order_by(Work.created_at.desc()).all()
    return render_template("work/index.html", works=works)


@bp.route("/new", methods=["GET", "POST"])
def new():
    """作品新規。"""
    characters = Character.query.order_by(Character.name).all()
    stories = Story.query.order_by(Story.created_at.desc()).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        cid = request.form.get("character_id", type=int)
        if not title or not cid:
            flash("タイトルとキャラクターを入力してください。", "error")
            return render_template(
                "work/form.html",
                work=None,
                characters=characters,
                stories=stories,
            )

        story_id = request.form.get("story_id", type=int) or None
        w = Work(
            character_id=cid,
            title=title,
            status=request.form.get("status") or Work.STATUS_GENERATING,
            price=int(request.form.get("price") or 0),
            pixiv_url=request.form.get("pixiv_url", "").strip() or None,
            pict_url=request.form.get("pict_url", "").strip() or None,
            dl_url=request.form.get("dl_url", "").strip() or None,
            sales_pict=int(request.form.get("sales_pict") or 0),
            sales_dl=int(request.form.get("sales_dl") or 0),
            story_id=story_id,
        )
        db.session.add(w)
        db.session.commit()
        flash("作品を登録しました。", "success")
        return redirect(url_for("work.index"))

    return render_template(
        "work/form.html",
        work=None,
        characters=characters,
        stories=stories,
    )


@bp.route("/<int:wid>/edit", methods=["GET", "POST"])
def edit(wid: int):
    """作品編集。"""
    work = Work.query.get_or_404(wid)
    characters = Character.query.order_by(Character.name).all()
    stories = Story.query.order_by(Story.created_at.desc()).all()

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        cid = request.form.get("character_id", type=int)
        if not title or not cid:
            flash("タイトルとキャラクターを入力してください。", "error")
            return render_template(
                "work/form.html",
                work=work,
                characters=characters,
                stories=stories,
            )

        work.character_id = cid
        work.title = title
        work.status = request.form.get("status") or work.status
        work.price = int(request.form.get("price") or 0)
        work.pixiv_url = request.form.get("pixiv_url", "").strip() or None
        work.pict_url = request.form.get("pict_url", "").strip() or None
        work.dl_url = request.form.get("dl_url", "").strip() or None
        work.sales_pict = int(request.form.get("sales_pict") or 0)
        work.sales_dl = int(request.form.get("sales_dl") or 0)
        work.story_id = request.form.get("story_id", type=int) or None
        db.session.commit()
        flash("作品を更新しました。", "success")
        return redirect(url_for("work.index"))

    return render_template(
        "work/form.html",
        work=work,
        characters=characters,
        stories=stories,
    )


@bp.route("/<int:wid>/delete", methods=["POST"])
def delete(wid: int):
    """作品削除。"""
    work = Work.query.get_or_404(wid)
    db.session.delete(work)
    db.session.commit()
    flash("作品を削除しました。", "success")
    return redirect(url_for("work.index"))
