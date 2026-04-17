"""ダッシュボード（集計・クイックリンク）。"""

from flask import Blueprint, redirect, render_template, request, url_for
from sqlalchemy import func
from sqlalchemy.orm import selectinload

from app import db
from app.models.character import Character
from app.models.image import Image
from app.models.prompt import Prompt
from app.models.sales import SalesRecord
from app.models.story import Story
from app.models.work import Work

bp = Blueprint("dashboard", __name__)


def _safe_internal_redirect(raw: str | None) -> str:
    """オープンリダイレクト防止: 同一オリジン内のパスのみ。"""
    s = (raw or "").strip()
    if not s or not s.startswith("/") or s.startswith("//"):
        return url_for("dashboard.index")
    return s


@bp.route("/set-ui-theme", methods=["POST"])
def set_ui_theme():
    """画面テーマ（ライト / ダーク）を Cookie に保存して元ページへ戻す。"""
    next_url = _safe_internal_redirect(request.form.get("next"))
    choice = (request.form.get("theme") or "light").strip().lower()
    theme = "dark" if choice == "dark" else "light"
    resp = redirect(next_url)
    resp.set_cookie(
        "portal_ui_theme",
        theme,
        max_age=31536000,
        path="/",
        samesite="Lax",
    )
    return resp


@bp.route("/")
def index():
    """ダッシュボードのトップ。"""
    work_count = db.session.query(Work).count()
    character_count = db.session.query(Character).count()
    story_count = db.session.query(Story).count()
    image_count = db.session.query(Image).count()
    prompt_count = db.session.query(Prompt).count()

    recent_works = (
        Work.query.order_by(Work.created_at.desc()).limit(5).all()
    )
    recent_stories = (
        Story.query.order_by(Story.created_at.desc()).limit(5).all()
    )
    sales_rows = (
        SalesRecord.query.options(selectinload(SalesRecord.expense_items))
        .order_by(SalesRecord.month.desc())
        .limit(6)
        .all()
    )

    revenue_expr = (Work.sales_pict + Work.sales_dl) * Work.price
    total_revenue_works = int(
        db.session.query(func.coalesce(func.sum(revenue_expr), 0)).scalar() or 0
    )

    return render_template(
        "dashboard/index.html",
        work_count=work_count,
        character_count=character_count,
        story_count=story_count,
        image_count=image_count,
        prompt_count=prompt_count,
        recent_works=recent_works,
        recent_stories=recent_stories,
        sales_rows=sales_rows,
        total_revenue_works=total_revenue_works,
    )
