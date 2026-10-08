"""T4: dialogue_scenes (自定义自由对话场景) + generation_jobs.kind

计划 §3 C1/C3:

* ``dialogue_scenes``  学员自己描述的自由对话场景骨架 (per-user), 形状照
  ``scene_courses``: ``scene_key`` (brief 指纹) 做 ``(user_id, scene_key)`` 唯一去重,
  ``doc`` 存 ``CustomDialogueScene`` JSON。``status`` 三态
  ``generating``/``ready``/``failed``; 目录列表只放 ``ready``。
* ``generation_jobs.kind``  两种生成任务共存一张 job 表 (``course`` 整课生成 /
  ``scene_brief`` 自定义对话场景), 靠这一列区分 —— 否则 ``GET /scenes/jobs/{id}``
  会把两种 job 混成一种。既有行按 ``server_default`` 回填 ``course``。

``doc`` 用 ``sqlalchemy.JSON`` (**不是** JSONB): sqlite 测试与 PG16 生产同一份 DDL
(与 M1/M2/M3 同一口径)。``kind`` 的 ``server_default`` 保留不撤 —— 加列时的回填
与新库都靠它, 两边方言都渲染得出。

Revision ID: c3b7e5a91d24
Revises: 9d2e4c6a8f01
Create Date: 2026-10-10 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3b7e5a91d24"
down_revision: str | None = "9d2e4c6a8f01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "dialogue_scenes",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scene_key", sa.String(length=64), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        # generating | ready | failed
        sa.Column("status", sa.String(length=16), nullable=False, server_default="generating"),
        # generated = LLM 按 brief 生成 (预留给将来的手写/导入)
        sa.Column("source", sa.String(length=16), nullable=False, server_default="generated"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dialogue_scenes_status", "dialogue_scenes", ["status"], unique=False)
    op.create_index("ix_dialogue_scenes_user_id", "dialogue_scenes", ["user_id"], unique=False)
    op.create_index(
        "ix_dialogue_scenes_user_scene_key",
        "dialogue_scenes",
        ["user_id", "scene_key"],
        unique=True,
    )

    # 既有 generation_jobs 行是整课生成 -> 回填 "course" (server_default 一次做两件事:
    # 回填旧行 + 给不带该列的未来插入兜底).
    op.add_column(
        "generation_jobs",
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="course"),
    )


def downgrade() -> None:
    # sqlite 上 ALTER TABLE DROP COLUMN 的历史版本差异太大, 走 batch (copy-and-recreate),
    # PG 上 alembic 直接下发 ALTER TABLE ... DROP COLUMN (batch 在那边也是直改)。
    with op.batch_alter_table("generation_jobs") as batch_op:
        batch_op.drop_column("kind")

    op.drop_index("ix_dialogue_scenes_user_scene_key", table_name="dialogue_scenes")
    op.drop_index("ix_dialogue_scenes_user_id", table_name="dialogue_scenes")
    op.drop_index("ix_dialogue_scenes_status", table_name="dialogue_scenes")
    op.drop_table("dialogue_scenes")
