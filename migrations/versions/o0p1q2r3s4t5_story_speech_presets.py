"""stories にセリフプリセット10枠、予約ジョブにプリセット番号

Revision ID: o0p1q2r3s4t5
Revises: n7o8p9q0r1s2
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa


revision = "o0p1q2r3s4t5"
down_revision = "n7o8p9q0r1s2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "stories",
        sa.Column("speech_presets_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("speech_preset_index", sa.Integer(), nullable=True),
    )


def downgrade():
    op.drop_column("scheduled_image_jobs", "speech_preset_index")
    op.drop_column("stories", "speech_presets_json")
