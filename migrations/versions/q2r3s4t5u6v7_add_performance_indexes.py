"""パフォーマンス改善用インデックス追加

Revision ID: q2r3s4t5u6v7
Revises: p1q2r3s4t5u6
Create Date: 2026-04-18
"""

from alembic import op
import sqlalchemy as sa

revision = "q2r3s4t5u6v7"
down_revision = "p1q2r3s4t5u6"
branch_labels = None
depends_on = None


def _existing_index_names(bind, table: str) -> set[str]:
    try:
        insp = sa.inspect(bind)
        return {ix["name"] for ix in (insp.get_indexes(table) or [])}
    except sa.exc.NoSuchTableError:
        return set()


def upgrade():
    bind = op.get_bind()

    names = _existing_index_names(bind, "images")
    if "ix_images_story_id" not in names:
        op.create_index(
            "ix_images_story_id",
            "images",
            ["story_id"],
            unique=False,
        )
    if "ix_images_created_at" not in names:
        op.create_index(
            "ix_images_created_at",
            "images",
            ["created_at"],
            unique=False,
        )

    names = _existing_index_names(bind, "stories")
    if "ix_stories_created_at" not in names:
        op.create_index(
            "ix_stories_created_at",
            "stories",
            ["created_at"],
            unique=False,
        )
    if "ix_stories_character_id" not in names:
        op.create_index(
            "ix_stories_character_id",
            "stories",
            ["character_id"],
            unique=False,
        )

    names = _existing_index_names(bind, "prompts")
    if "ix_prompts_character_id" not in names:
        op.create_index(
            "ix_prompts_character_id",
            "prompts",
            ["character_id"],
            unique=False,
        )
    if "ix_prompts_starred_created" not in names:
        op.create_index(
            "ix_prompts_starred_created",
            "prompts",
            ["is_starred", "created_at"],
            unique=False,
        )

    names = _existing_index_names(bind, "works")
    if "ix_works_created_at" not in names:
        op.create_index(
            "ix_works_created_at",
            "works",
            ["created_at"],
            unique=False,
        )

    names = _existing_index_names(bind, "flow_tasks")
    if "ix_flow_tasks_done_due" not in names:
        op.create_index(
            "ix_flow_tasks_done_due",
            "flow_tasks",
            ["done", "due_date"],
            unique=False,
        )


def downgrade():
    op.drop_index("ix_flow_tasks_done_due", table_name="flow_tasks")
    op.drop_index("ix_works_created_at", table_name="works")
    op.drop_index("ix_prompts_starred_created", table_name="prompts")
    op.drop_index("ix_prompts_character_id", table_name="prompts")
    op.drop_index("ix_stories_character_id", table_name="stories")
    op.drop_index("ix_stories_created_at", table_name="stories")
    op.drop_index("ix_images_created_at", table_name="images")
    op.drop_index("ix_images_story_id", table_name="images")
