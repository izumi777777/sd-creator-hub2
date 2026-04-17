"""sales_records に hosting_expense / other_expense

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("sales_records", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("hosting_expense", sa.Integer(), nullable=True, server_default="0")
        )
        batch_op.add_column(
            sa.Column("other_expense", sa.Integer(), nullable=True, server_default="0")
        )


def downgrade():
    with op.batch_alter_table("sales_records", schema=None) as batch_op:
        batch_op.drop_column("other_expense")
        batch_op.drop_column("hosting_expense")
