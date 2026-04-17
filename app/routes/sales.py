"""月次売上記録の CRUD。"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from app import db
from app.models.sales import SalesRecord
from app.models.sales_expense_item import SalesExpenseItem

bp = Blueprint("sales", __name__)


def _int_ge0(name: str, default: int = 0) -> int:
    """フォームから非負整数を取り出す。"""
    raw = request.form.get(name)
    try:
        v = int(raw) if raw is not None and str(raw).strip() != "" else default
    except ValueError:
        return default
    return max(0, v)


def _parse_expense_rows_from_form() -> list[tuple[str, int]]:
    """expense_label / expense_amount の並びから (項目名, 円) のリストを返す。"""
    labels = request.form.getlist("expense_label")
    amounts = request.form.getlist("expense_amount")
    out: list[tuple[str, int]] = []
    n = max(len(labels), len(amounts))
    for idx in range(n):
        raw_l = (labels[idx] if idx < len(labels) else "") or ""
        raw_l = raw_l.strip()[:120]
        raw_a = amounts[idx] if idx < len(amounts) else ""
        try:
            amt = int(raw_a) if str(raw_a).strip() != "" else 0
        except ValueError:
            continue
        amt = max(0, amt)
        if amt == 0 and not raw_l:
            continue
        if not raw_l:
            raw_l = "（項目名未入力）"
        out.append((raw_l, amt))
    return out


def _apply_expense_items(record: SalesRecord, rows: list[tuple[str, int]]) -> None:
    record.expense_items.clear()
    for i, (lbl, amt) in enumerate(rows):
        record.expense_items.append(
            SalesExpenseItem(label=lbl, amount=amt, sort_order=i)
        )


@bp.route("/")
def index():
    """売上一覧（新しい月順）。"""
    records = (
        SalesRecord.query.options(selectinload(SalesRecord.expense_items))
        .order_by(SalesRecord.month.desc())
        .all()
    )
    sum_revenue = sum(r.total for r in records)
    sum_expenses = sum(r.total_expenses for r in records)
    sum_net = sum(r.net for r in records)
    return render_template(
        "sales/index.html",
        records=records,
        sum_revenue=sum_revenue,
        sum_expenses=sum_expenses,
        sum_net=sum_net,
    )


@bp.route("/new", methods=["GET", "POST"])
def new():
    """月次レコード新規。"""
    if request.method == "POST":
        month = request.form.get("month", "").strip()
        if not month or len(month) != 7:
            flash("月は YYYY-MM 形式で入力してください。", "error")
            return render_template("sales/form.html", record=None)

        rows = _parse_expense_rows_from_form()
        rec = SalesRecord(
            month=month,
            pict_revenue=_int_ge0("pict_revenue"),
            dl_revenue=_int_ge0("dl_revenue"),
            followers=_int_ge0("followers"),
        )
        _apply_expense_items(rec, rows)
        db.session.add(rec)
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("同じ月（YYYY-MM）のレコードが既に存在します。", "error")
            return render_template("sales/form.html", record=None)

        flash("売上レコードを追加しました。", "success")
        return redirect(url_for("sales.index"))

    return render_template("sales/form.html", record=None)


@bp.route("/<int:rid>/edit", methods=["GET", "POST"])
def edit(rid: int):
    """売上レコード編集。"""
    record = SalesRecord.query.options(selectinload(SalesRecord.expense_items)).get_or_404(
        rid
    )
    if request.method == "POST":
        month = request.form.get("month", "").strip()
        if not month or len(month) != 7:
            flash("月は YYYY-MM 形式で入力してください。", "error")
            return render_template("sales/form.html", record=record)

        record.month = month
        record.pict_revenue = _int_ge0("pict_revenue")
        record.dl_revenue = _int_ge0("dl_revenue")
        record.followers = _int_ge0("followers")
        _apply_expense_items(record, _parse_expense_rows_from_form())
        try:
            db.session.commit()
        except IntegrityError:
            db.session.rollback()
            flash("同じ月（YYYY-MM）の別レコードが既に存在します。", "error")
            return render_template("sales/form.html", record=record)

        flash("売上レコードを更新しました。", "success")
        return redirect(url_for("sales.index"))

    return render_template("sales/form.html", record=record)


@bp.route("/<int:rid>/delete", methods=["POST"])
def delete(rid: int):
    """売上レコード削除。"""
    record = SalesRecord.query.get_or_404(rid)
    db.session.delete(record)
    db.session.commit()
    flash("売上レコードを削除しました。", "success")
    return redirect(url_for("sales.index"))
