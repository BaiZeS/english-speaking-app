"""v3.0: dialogue_threads (微信式情景对话的会话线程)

「回到这个场景接着聊」的落库面: 一个用户在一个场景上只有一条会话
(``(user_id, scene_key)`` 唯一), 消息全在 ``doc`` JSON 里。

``doc`` 用 ``sqlalchemy.JSON`` (**不是** JSONB): sqlite 测试与 PG16 生产同一份 DDL
(与 M1/M2/M3/``dialogue_scenes`` 同一口径)。``revision`` 是乐观锁列, 建表即 NOT NULL
且给 ``server_default`` —— 既有表加 NOT NULL 列要靠默认值回填, 新表则保证两条方言
都渲染得出同一句 DDL。

Revision ID: e7a2c4f0b913
Revises: c3b7e5a91d24
Create Date: 2026-10-30 11:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7a2c4f0b913"
down_revision: str | None = "c3b7e5a91d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dialogue_threads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        # 目录场景 id 或 custom_<row_id>
        sa.Column("scene_key", sa.String(length=64), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.Column("turn_count", sa.Integer(), nullable=False, server_default="0"),
        # "" | pending | ready | failed
        sa.Column("grading_status", sa.String(length=16), nullable=False, server_default=""),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dialogue_threads_user_id", "dialogue_threads", ["user_id"], unique=False)
    op.create_index(
        "ix_dialogue_threads_grading_status",
        "dialogue_threads",
        ["grading_status"],
        unique=False,
    )
    op.create_index(
        "ix_dialogue_threads_user_scene_key",
        "dialogue_threads",
        ["user_id", "scene_key"],
        unique=True,
    )
    op.create_index(
        "ix_dialogue_threads_user_recency",
        "dialogue_threads",
        ["user_id", "updated_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_dialogue_threads_user_recency", table_name="dialogue_threads")
    op.drop_index("ix_dialogue_threads_user_scene_key", table_name="dialogue_threads")
    op.drop_index("ix_dialogue_threads_grading_status", table_name="dialogue_threads")
    op.drop_index("ix_dialogue_threads_user_id", table_name="dialogue_threads")
    op.drop_table("dialogue_threads")
