"""scheduled_image_jobs に batch_size / n_iter

Revision ID: i2b3c4d5e6f7
Revises: h1b2c3d4e5f6
Create Date: 2026-04-16

"""

from alembic import op
import sqlalchemy as sa


revision = "i2b3c4d5e6f7"
down_revision = "h1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("batch_size", sa.Integer(), nullable=False, server_default="1"),
    )
    op.add_column(
        "scheduled_image_jobs",
        sa.Column("n_iter", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade():
    op.drop_column("scheduled_image_jobs", "n_iter")
    op.drop_column("scheduled_image_jobs", "batch_size")
