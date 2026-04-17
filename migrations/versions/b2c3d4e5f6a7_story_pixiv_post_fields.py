"""story Pixiv 投稿文案フィールド

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("stories", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("pixiv_post_title", sa.String(length=500), nullable=True)
        )
        batch_op.add_column(sa.Column("pixiv_post_caption", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("pixiv_post_tags", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("stories", schema=None) as batch_op:
        batch_op.drop_column("pixiv_post_tags")
        batch_op.drop_column("pixiv_post_caption")
        batch_op.drop_column("pixiv_post_title")
