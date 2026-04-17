"""stored_documents テーブル（PDF 等）

Revision ID: f1e2d3c4b5a6
Revises: e5f6a7b8c9d0
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = "f1e2d3c4b5a6"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stored_documents",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("doc_category", sa.String(length=20), nullable=False),
        sa.Column("related_month", sa.String(length=7), nullable=True),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("s3_key", sa.String(length=500), nullable=False),
        sa.Column("s3_url", sa.String(length=500), nullable=True),
        sa.Column("mime_type", sa.String(length=120), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade():
    op.drop_table("stored_documents")
