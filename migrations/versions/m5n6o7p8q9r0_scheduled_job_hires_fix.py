"""scheduled_image_jobs に Hi-res fix 用カラム

Revision ID: m5n6o7p8q9r0
Revises: j3k4l5m6n7o8
Create Date: 2026-04-16

"""

from alembic import op
import sqlalchemy as sa


revision = "m5n6o7p8q9r0"
down_revision = "j3k4l5m6n7o8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("enable_hr", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("hr_scale", sa.Float(), nullable=False, server_default="2"),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column(
            "hr_denoising_strength",
            sa.Float(),
            nullable=False,
            server_default="0.5",
        ),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("hr_second_pass_steps", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("hr_upscaler", sa.String(length=120), nullable=True),
    )


def downgrade():
    op.drop_column("scheduled_image_jobs", "hr_upscaler")
    op.drop_column("scheduled_image_jobs", "hr_second_pass_steps")
    op.drop_column("scheduled_image_jobs", "hr_denoising_strength")
    op.drop_column("scheduled_image_jobs", "hr_scale")
    op.drop_column("scheduled_image_jobs", "enable_hr")
