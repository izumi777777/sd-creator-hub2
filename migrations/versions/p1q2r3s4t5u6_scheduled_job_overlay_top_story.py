"""scheduled_image_jobs に上段ストーリー焼き込み有無

Revision ID: p1q2r3s4t5u6
Revises: o0p1q2r3s4t5
Create Date: 2026-04-17
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "p1q2r3s4t5u6"
down_revision = "o0p1q2r3s4t5"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("scheduled_image_jobs")}
    if "overlay_include_top_story" in cols:
        return
    op.add_column(
        "scheduled_image_jobs",
        sa.Column(
            "overlay_include_top_story",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.alter_column(
        "scheduled_image_jobs",
        "overlay_include_top_story",
        server_default=None,
    )


def downgrade():
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns("scheduled_image_jobs")}
    if "overlay_include_top_story" not in cols:
        return
    op.drop_column("scheduled_image_jobs", "overlay_include_top_story")
