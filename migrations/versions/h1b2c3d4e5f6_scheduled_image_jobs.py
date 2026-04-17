"""scheduled_image_jobs（画像生成の日時予約）

Revision ID: h1b2c3d4e5f6
Revises: f1e2d3c4b5a6
Create Date: 2026-04-16

"""

from alembic import op
import sqlalchemy as sa


revision = "h1b2c3d4e5f6"
down_revision = "f1e2d3c4b5a6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "scheduled_image_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("story_id", sa.Integer(), nullable=False),
        sa.Column("character_id", sa.Integer(), nullable=False),
        sa.Column("ch_no", sa.Integer(), nullable=False),
        sa.Column("variant_index", sa.Integer(), nullable=True),
        sa.Column("steps", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="512"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="768"),
        sa.Column("seed", sa.Integer(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"]),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_scheduled_image_jobs_status_scheduled",
        "scheduled_image_jobs",
        ["status", "scheduled_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_scheduled_image_jobs_status_scheduled", table_name="scheduled_image_jobs")
    op.drop_table("scheduled_image_jobs")
