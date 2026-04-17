"""image story_id and storage_folder for S3 subdirs

Revision ID: a1b2c3d4e5f6
Revises: 021cba9c6779
Create Date: 2026-04-05

"""
from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "021cba9c6779"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("images", schema=None) as batch_op:
        batch_op.add_column(sa.Column("story_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("storage_folder", sa.String(length=20), nullable=True))
        batch_op.create_foreign_key(
            "fk_images_story_id",
            "stories",
            ["story_id"],
            ["id"],
        )


def downgrade():
    with op.batch_alter_table("images", schema=None) as batch_op:
        batch_op.drop_constraint("fk_images_story_id", type_="foreignkey")
        batch_op.drop_column("storage_folder")
        batch_op.drop_column("story_id")
