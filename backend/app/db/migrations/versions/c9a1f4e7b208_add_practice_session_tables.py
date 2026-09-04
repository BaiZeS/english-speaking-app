"""M1: scene_courses + practice_sessions + practice_steps

v2.0 计划 §5.2 M1 —— 情景课通关闭环的三张表, 全部 add-only (不动任何既有表):

* ``scene_courses``       LLM 生成的 per-user 情景课 (curated 走磁盘文件).
  ``doc`` 存完整 ``SceneCourse`` JSON; ``(user_id, scene_key)`` 唯一索引做同目标去重.
* ``practice_sessions``   会话状态机快照. 客户端只发音频, 状态由服务端 ``doc`` 持有
  (计划 §四: 省流量 / 防篡改 / 崩溃可恢复). ``revision`` 是乐观锁版本列;
  ``(user_id, status, last_active_at DESC)`` 支撑首页「继续学习」.
* ``practice_steps``      逐步证据. 6 个分数列**全部可空**: NULL = 本题型该维度没有
  证据 (§5.6 画像门控的前提), 不是 0 分.

JSON 列用 ``sqlalchemy.JSON``: 测试跑 sqlite、生产跑 PG16, 同一份 DDL 两边都得能建.

Revision ID: c9a1f4e7b208
Revises: a3f7c9d21b45
Create Date: 2026-09-04 10:20:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9a1f4e7b208"
down_revision: str | None = "a3f7c9d21b45"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scene_courses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scene_key", sa.String(length=64), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scene_courses_status", "scene_courses", ["status"], unique=False)
    op.create_index("ix_scene_courses_user_id", "scene_courses", ["user_id"], unique=False)
    op.create_index(
        "ix_scene_courses_user_scene_key",
        "scene_courses",
        ["user_id", "scene_key"],
        unique=True,
    )

    op.create_table(
        "practice_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("doc", sa.JSON(), nullable=False),
        # 乐观锁版本列 (SQLAlchemy version_id_col); 新表逐行从 1 起.
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("owner_device_id", sa.String(length=128), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_sessions_user_id", "practice_sessions", ["user_id"])
    # 「继续学习」/ 会话列表: user + status 过滤, 最近活跃倒序.
    # sa.text 片段两个方言都渲染成 `last_active_at DESC` (PG 与 sqlite 都支持索引列排序).
    op.create_index(
        "ix_practice_sessions_user_status_recency",
        "practice_sessions",
        ["user_id", "status", sa.text("last_active_at DESC")],
    )
    op.create_index(
        "ix_practice_sessions_user_scene",
        "practice_sessions",
        ["user_id", "scene_id"],
    )

    op.create_table(
        "practice_steps",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=32), nullable=False),
        sa.Column("step_index", sa.Integer(), nullable=False),
        sa.Column("step_type", sa.String(length=32), nullable=False),
        sa.Column("attempt", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("score_total", sa.Float(), nullable=True),
        sa.Column("score_pronunciation", sa.Float(), nullable=True),
        sa.Column("score_fluency", sa.Float(), nullable=True),
        sa.Column("score_completeness", sa.Float(), nullable=True),
        sa.Column("score_grammar", sa.Float(), nullable=True),
        sa.Column("score_vocabulary", sa.Float(), nullable=True),
        sa.Column("ise_ref_mode", sa.String(length=32), nullable=True),
        sa.Column("annotated_json", sa.JSON(), nullable=True),
        sa.Column("speech_rate_wpm", sa.Float(), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("llm_source", sa.String(length=64), nullable=True),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["practice_sessions.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_practice_steps_session_id", "practice_steps", ["session_id"])
    op.create_index("ix_practice_steps_user_id", "practice_steps", ["user_id"])
    op.create_index(
        "ix_practice_steps_session_step",
        "practice_steps",
        ["session_id", "step_index"],
    )


def downgrade() -> None:
    op.drop_index("ix_practice_steps_session_step", table_name="practice_steps")
    op.drop_index("ix_practice_steps_user_id", table_name="practice_steps")
    op.drop_index("ix_practice_steps_session_id", table_name="practice_steps")
    op.drop_table("practice_steps")
    op.drop_index("ix_practice_sessions_user_scene", table_name="practice_sessions")
    op.drop_index("ix_practice_sessions_user_status_recency", table_name="practice_sessions")
    op.drop_index("ix_practice_sessions_user_id", table_name="practice_sessions")
    op.drop_table("practice_sessions")
    op.drop_index("ix_scene_courses_user_scene_key", table_name="scene_courses")
    op.drop_index("ix_scene_courses_user_id", table_name="scene_courses")
    op.drop_index("ix_scene_courses_status", table_name="scene_courses")
    op.drop_table("scene_courses")
