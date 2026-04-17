"""月次売上に紐づく経費行（項目名＋金額）。"""

from app import db


class SalesExpenseItem(db.Model):
    """1 ヶ月あたり任意件数の経費明細。"""

    __tablename__ = "sales_expense_items"

    id = db.Column(db.Integer, primary_key=True)
    sales_record_id = db.Column(
        db.Integer,
        db.ForeignKey("sales_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    label = db.Column(db.String(120), nullable=False)
    amount = db.Column(db.Integer, nullable=False, default=0)
    sort_order = db.Column(db.Integer, nullable=False, default=0)

    sales_record = db.relationship(
        "SalesRecord", back_populates="expense_items"
    )
