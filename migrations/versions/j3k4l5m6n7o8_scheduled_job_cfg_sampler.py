"""scheduled_image_jobs に cfg_scale / sampler_name

Revision ID: j3k4l5m6n7o8
Revises: i2b3c4d5e6f7
Create Date: 2026-04-12

"""

from alembic import op
import sqlalchemy as sa


revision = "j3k4l5m6n7o8"
down_revision = "i2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("cfg_scale", sa.Float(), nullable=False, server_default="7"),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column(
            "sampler_name",
            sa.String(length=80),
            nullable=False,
            server_default=sa.text("'Euler a'"),
        ),
    )


def downgrade():
    op.drop_column("scheduled_image_jobs", "sampler_name")
    op.drop_column("scheduled_image_jobs", "cfg_scale")
