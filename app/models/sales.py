"""月次売上記録モデル。"""

from datetime import datetime

from app import db


class SalesRecord(db.Model):
    """月次売上記録。"""

    __tablename__ = "sales_records"
    __table_args__ = (db.UniqueConstraint("month", name="uq_sales_month"),)

    id = db.Column(db.Integer, primary_key=True)
    month = db.Column(db.String(7), nullable=False)
    pict_revenue = db.Column(db.Integer, default=0)
    dl_revenue = db.Column(db.Integer, default=0)
    followers = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    expense_items = db.relationship(
        "SalesExpenseItem",
        back_populates="sales_record",
        cascade="all, delete-orphan",
        order_by="SalesExpenseItem.sort_order",
    )

    @property
    def total(self) -> int:
        """プラットフォーム売上の合計。"""
        return self.pict_revenue + self.dl_revenue

    @property
    def total_expenses(self) -> int:
        """月次支出の合計（明細行の合算）。"""
        items = self.expense_items
        if not items:
            return 0
        return sum((i.amount or 0) for i in items)

    @property
    def net(self) -> int:
        """売上合計 − 支出合計（粗利イメージ。税・経費の厳密な会計ではない）。"""
        return self.total - self.total_expenses
