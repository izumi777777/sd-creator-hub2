"""制作フロー: 手動タスクと DB 上の自動イベントを時系列・カレンダー表示。"""

import calendar as cal_std
from calendar import Calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for

from app import db
from app.models.flow_task import FlowTask
from app.models.image import Image
from app.models.story import Story
from app.models.work import Work

bp = Blueprint("flow", __name__)

_CATEGORY_FORM = {
    "generate": FlowTask.CATEGORY_GENERATE,
    "post": FlowTask.CATEGORY_POST,
    "other": FlowTask.CATEGORY_OTHER,
}


def _story_filter_id() -> int | None:
    raw = request.args.get("story_id", type=int)
    if raw and raw > 0:
        return raw
    return None


def _auto_timeline_entries(story_id: int | None) -> list[dict]:
    """ストーリー紐づけの作成・画像登録・作品登録を時系列用に集める。"""
    entries: list[dict] = []

    qs = Story.query
    if story_id:
        qs = qs.filter(Story.id == story_id)
    for s in qs.order_by(Story.created_at.desc()).all():
        if not s.created_at:
            continue
        entries.append(
            {
                "sort_at": s.created_at,
                "kind": "story",
                "label": "ストーリー作成",
                "title": s.title or f"#{s.id}",
                "href": url_for("story.detail", sid=s.id),
            }
        )

    qi = Image.query.filter(Image.story_id.isnot(None))
    if story_id:
        qi = qi.filter(Image.story_id == story_id)
    for im in qi.order_by(Image.created_at.desc()).limit(400).all():
        if not im.created_at:
            continue
        st = im.story
        stitle = (st.title if st else None) or f"story #{im.story_id}"
        entries.append(
            {
                "sort_at": im.created_at,
                "kind": "image",
                "label": "画像登録（ストーリー紐づけ）",
                "title": im.file_name or f"画像 #{im.id} · {stitle}",
                "href": url_for("image.preview", iid=im.id)
                if im.s3_key or im.s3_url
                else url_for("story.detail", sid=im.story_id)
                if im.story_id
                else None,
            }
        )

    qw = Work.query.filter(Work.story_id.isnot(None))
    if story_id:
        qw = qw.filter(Work.story_id == story_id)
    for w in qw.order_by(Work.created_at.desc()).all():
        if not w.created_at:
            continue
        entries.append(
            {
                "sort_at": w.created_at,
                "kind": "work",
                "label": "作品登録（ストーリー紐づけ）",
                "title": w.title,
                "href": url_for("work.edit", wid=w.id),
            }
        )

    entries.sort(key=lambda e: e["sort_at"], reverse=True)
    return entries


def _flow_tasks_query(story_id: int | None):
    q = FlowTask.query
    if story_id:
        q = q.filter((FlowTask.story_id == story_id) | (FlowTask.story_id.is_(None)))
    return q


def _pending_tasks_sorted(story_id: int | None) -> list[FlowTask]:
    rows = _flow_tasks_query(story_id).filter_by(done=False).all()
    max_d = date.max

    def sort_key(t: FlowTask):
        return (t.due_date is None, t.due_date or max_d, t.id)

    rows.sort(key=sort_key)
    return rows


def _completed_task_entries(story_id: int | None) -> list[dict]:
    out: list[dict] = []
    for t in _flow_tasks_query(story_id).filter_by(done=True).all():
        if not t.done_at:
            continue
        out.append(
            {
                "sort_at": t.done_at,
                "kind": "task_done",
                "label": f"タスク完了（{t.category_label}）",
                "title": t.title,
                "href": None,
            }
        )
    out.sort(key=lambda e: e["sort_at"], reverse=True)
    return out


def _merge_timeline(auto: list[dict], completed: list[dict]) -> list[dict]:
    merged = list(auto) + list(completed)
    merged.sort(key=lambda e: e["sort_at"], reverse=True)
    return merged


def _calendar_weeks(year: int, month: int) -> list[list[date]]:
    cal = Calendar(firstweekday=cal_std.SUNDAY)
    return cal.monthdatescalendar(year, month)


def _day_counts(
    auto: list[dict],
    tasks: list[FlowTask],
    year: int,
    month: int,
) -> dict[date, dict[str, int]]:
    """月内の各日について、種別ごとの件数。"""
    first = date(year, month, 1)
    if month == 12:
        last = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        last = date(year, month + 1, 1) - timedelta(days=1)

    counts: dict[date, dict[str, int]] = defaultdict(
        lambda: {"story": 0, "image": 0, "work": 0, "task": 0, "task_done": 0}
    )

    for e in auto:
        d = e["sort_at"].date()
        if first <= d <= last:
            k = e["kind"]
            if k in counts[d]:
                counts[d][k] += 1

    for t in tasks:
        if t.due_date and first <= t.due_date <= last:
            counts[t.due_date]["task"] += 1
        if t.done and t.done_at:
            d = t.done_at.date()
            if first <= d <= last:
                counts[d]["task_done"] += 1

    return counts


def _items_for_day(
    target: date,
    auto: list[dict],
    all_tasks: list[FlowTask],
) -> tuple[list[dict], list[FlowTask]]:
    """指定日の自動イベント行とタスク（予定日または完了日がその日）。"""
    day_auto = [e for e in auto if e["sort_at"].date() == target]
    day_auto.sort(key=lambda e: e["sort_at"], reverse=True)

    seen: set[int] = set()
    day_tasks: list[FlowTask] = []
    for t in all_tasks:
        on_due = t.due_date == target
        on_done = t.done and t.done_at and t.done_at.date() == target
        if (on_due or on_done) and t.id not in seen:
            seen.add(t.id)
            day_tasks.append(t)
    day_tasks.sort(key=lambda t: (t.done, t.due_date is None, t.id))
    return day_auto, day_tasks


@bp.route("/flow")
def index():
    story_id = _story_filter_id()
    view = (request.args.get("view") or "list").strip().lower()
    if view not in ("list", "calendar"):
        view = "list"

    today = date.today()
    year = request.args.get("year", type=int) or today.year
    month = request.args.get("month", type=int) or today.month
    if month < 1 or month > 12:
        month = today.month
    if year < 2000 or year > 2100:
        year = today.year

    stories = Story.query.all()
    stories.sort(key=lambda s: ((s.title or "").lower(), s.id))
    auto = _auto_timeline_entries(story_id)
    completed_task_entries = _completed_task_entries(story_id)
    timeline = _merge_timeline(auto, completed_task_entries)
    pending = _pending_tasks_sorted(story_id)
    all_tasks = _flow_tasks_query(story_id).order_by(FlowTask.created_at.desc()).all()

    cal_weeks = _calendar_weeks(year, month)
    day_counts = _day_counts(auto, all_tasks, year, month)

    focus_day_raw = request.args.get("day")
    focus_day: date | None = None
    if focus_day_raw:
        try:
            y, m, d = (int(x) for x in focus_day_raw.split("-", 2))
            focus_day = date(y, m, d)
        except (ValueError, TypeError):
            focus_day = None
    if view == "calendar" and focus_day is None:
        focus_day = today if (today.year == year and today.month == month) else None

    day_auto: list[dict] = []
    day_tasks: list[FlowTask] = []
    if focus_day:
        day_auto, day_tasks = _items_for_day(focus_day, auto, all_tasks)

    prev_m = month - 1
    prev_y = year
    if prev_m < 1:
        prev_m = 12
        prev_y -= 1
    next_m = month + 1
    next_y = year
    if next_m > 12:
        next_m = 1
        next_y += 1

    return render_template(
        "flow/index.html",
        view=view,
        story_id=story_id,
        stories=stories,
        auto_entries=auto,
        timeline=timeline,
        pending_tasks=pending,
        year=year,
        month=month,
        cal_weeks=cal_weeks,
        day_counts=day_counts,
        today=today,
        focus_day=focus_day,
        day_auto=day_auto,
        day_tasks=day_tasks,
        prev_y=prev_y,
        prev_m=prev_m,
        next_y=next_y,
        next_m=next_m,
    )


@bp.route("/flow/tasks", methods=["POST"])
def add_task():
    title = (request.form.get("title") or "").strip()
    cat_key = (request.form.get("category") or "other").strip().lower()
    category = _CATEGORY_FORM.get(cat_key, FlowTask.CATEGORY_OTHER)
    notes = (request.form.get("notes") or "").strip() or None
    story_raw = request.form.get("attach_story_id", type=int)
    story_fk = story_raw if story_raw and story_raw > 0 else None
    due_raw = (request.form.get("due_date") or "").strip()
    due: date | None = None
    if due_raw:
        try:
            due = datetime.strptime(due_raw, "%Y-%m-%d").date()
        except ValueError:
            flash("予定日の形式が不正です（YYYY-MM-DD）。", "error")
            return redirect(_flow_redirect())

    if not title:
        flash("タイトルは必須です。", "error")
        return redirect(_flow_redirect())

    t = FlowTask(
        title=title,
        category=category,
        story_id=story_fk,
        due_date=due,
        notes=notes,
    )
    db.session.add(t)
    db.session.commit()
    flash("タスクを追加しました。", "success")
    return redirect(_flow_redirect())


def _flow_redirect() -> str:
    story_id = request.form.get("story_id_filter", type=int)
    view = (request.form.get("view") or "list").strip()
    args: dict = {}
    if story_id:
        args["story_id"] = story_id
    if view == "calendar":
        args["view"] = "calendar"
        y = request.form.get("year", type=int)
        m = request.form.get("month", type=int)
        if y:
            args["year"] = y
        if m:
            args["month"] = m
        d = (request.form.get("day") or "").strip()
        if d:
            args["day"] = d
    return url_for("flow.index", **args)


@bp.route("/flow/tasks/<int:tid>/toggle", methods=["POST"])
def toggle_task(tid: int):
    t = FlowTask.query.get_or_404(tid)
    if t.done:
        t.done = False
        t.done_at = None
        flash("タスクを未完了に戻しました。", "success")
    else:
        t.done = True
        t.done_at = datetime.utcnow()
        flash("タスクを完了にしました。", "success")
    db.session.commit()
    return redirect(_flow_redirect_from_task_form())


@bp.route("/flow/tasks/<int:tid>/delete", methods=["POST"])
def delete_task(tid: int):
    t = FlowTask.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    flash("タスクを削除しました。", "success")
    return redirect(_flow_redirect_from_task_form())


def _flow_redirect_from_task_form() -> str:
    story_id = request.form.get("story_id_filter", type=int)
    view = (request.form.get("view") or "list").strip()
    args: dict = {}
    if story_id:
        args["story_id"] = story_id
    if view == "calendar":
        args["view"] = "calendar"
        y = request.form.get("year", type=int)
        m = request.form.get("month", type=int)
        d = request.form.get("day", type=str)
        if y:
            args["year"] = y
        if m:
            args["month"] = m
        if d:
            args["day"] = d
    return url_for("flow.index", **args)
