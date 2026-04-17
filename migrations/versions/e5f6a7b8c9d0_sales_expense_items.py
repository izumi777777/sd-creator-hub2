"""経費を sales_expense_items 明細化し hosting/other 列を廃止

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "sales_expense_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sales_record_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(
            ["sales_record_id"],
            ["sales_records.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_sales_expense_items_sales_record_id",
        "sales_expense_items",
        ["sales_record_id"],
        unique=False,
    )

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT id, COALESCE(hosting_expense, 0), COALESCE(other_expense, 0) "
            "FROM sales_records"
        )
    )
    for rid, hosting, other in rows:
        so = 0
        if hosting and int(hosting) > 0:
            conn.execute(
                sa.text(
                    "INSERT INTO sales_expense_items (sales_record_id, label, amount, sort_order) "
                    "VALUES (:rid, :lb, :am, :so)"
                ),
                {
                    "rid": rid,
                    "lb": "サーバー・インフラ等（移行）",
                    "am": int(hosting),
                    "so": so,
                },
            )
            so += 1
        if other and int(other) > 0:
            conn.execute(
                sa.text(
                    "INSERT INTO sales_expense_items (sales_record_id, label, amount, sort_order) "
                    "VALUES (:rid, :lb, :am, :so)"
                ),
                {
                    "rid": rid,
                    "lb": "その他経費（移行）",
                    "am": int(other),
                    "so": so,
                },
            )

    with op.batch_alter_table("sales_records", schema=None) as batch_op:
        batch_op.drop_column("other_expense")
        batch_op.drop_column("hosting_expense")


def downgrade():
    with op.batch_alter_table("sales_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("hosting_expense", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("other_expense", sa.Integer(), nullable=True, server_default="0")
        )
    op.drop_index("ix_sales_expense_items_sales_record_id", table_name="sales_expense_items")
    op.drop_table("sales_expense_items")
