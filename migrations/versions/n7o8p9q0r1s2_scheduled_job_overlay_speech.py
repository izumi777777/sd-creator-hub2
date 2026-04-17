"""scheduled_image_jobs にセリフ焼き込み有無

Revision ID: n7o8p9q0r1s2
Revises: m5n6o7p8q9r0
Create Date: 2026-04-17

"""

from alembic import op
import sqlalchemy as sa


revision = "n7o8p9q0r1s2"
down_revision = "m5n6o7p8q9r0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_image_jobs",
        sa.Column(
            "overlay_include_speech",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("1"),
        ),
    )


def downgrade():
    op.drop_column("scheduled_image_jobs", "overlay_include_speech")
