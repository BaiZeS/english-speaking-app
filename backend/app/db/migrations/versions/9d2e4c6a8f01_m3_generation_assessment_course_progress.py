"""M3: generation_jobs + assessment_attempts/answers + course_progress

v2.0 计划 §5.2 M3 —— 生成任务 / CEFR 测评 / 通关进度, 全部 add-only:

* ``generation_jobs``      生成任务状态行 (``app.services.course_generator`` 后台
  任务逐段推进 ``progress``/``stage_text``, 客户端轮询); (user_id, created_at)
  索引支撑「我的生成任务」倒序扫。
* ``assessment_attempts``  一次 CEFR 测评 (start 建行, complete 写 result JSON);
* ``assessment_answers``   逐题作答, (attempt_id, question_no) 唯一 (重答覆盖);
  ``ise_score`` 只存真实 ISE (stub 的占位分不落库)。
* ``course_progress``      通关进度物化: (user_id, scene_id) 复合主键, 写侧走
  ``INSERT .. ON CONFLICT DO UPDATE`` (best_total 单调 / cleared 取或 / attempts
  自增) —— 画廊三字段直读这张表, 不做 GROUP BY (§5.2 原话)。

JSON/日期列沿用 M1/M2 口径: ``sqlalchemy.JSON`` (sqlite 测试与 PG16 生产双通),
只用到两边都渲得出的类型。

Revision ID: 9d2e4c6a8f01
Revises: f3b8d0716c52
Create Date: 2026-09-05 10:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "9d2e4c6a8f01"
down_revision: str | None = "f3b8d0716c52"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("goal_text", sa.Text(), nullable=False),
        sa.Column("category", sa.String(length=16), nullable=False),
        sa.Column("level", sa.String(length=8), nullable=False),
        # running | ready | failed
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("progress", sa.Float(), nullable=False),
        sa.Column("stage_text", sa.String(length=256), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_generation_jobs_user_id", "generation_jobs", ["user_id"], unique=False)
    op.create_index("ix_generation_jobs_status", "generation_jobs", ["status"], unique=False)
    op.create_index("ix_generation_jobs_user_created", "generation_jobs", ["user_id", "created_at"])

    op.create_table(
        "assessment_attempts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        # running | completed
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("answers_count", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_attempts_user_id", "assessment_attempts", ["user_id"], unique=False
    )

    op.create_table(
        "assessment_answers",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_id", sa.String(length=36), nullable=False),
        sa.Column("question_no", sa.Integer(), nullable=False),
        sa.Column("transcript", sa.Text(), nullable=False),
        # 只存真实 ISE 的分数 (stub 占位分不落库, 见模型 docstring).
        sa.Column("ise_score", sa.Float(), nullable=True),
        sa.Column("speech_rate_wpm", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["attempt_id"], ["assessment_attempts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_assessment_answers_attempt_id", "assessment_answers", ["attempt_id"], unique=False
    )
    op.create_index(
        "ux_assessment_answers_attempt_question",
        "assessment_answers",
        ["attempt_id", "question_no"],
        unique=True,
    )

    op.create_table(
        "course_progress",
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("cleared", sa.Boolean(), nullable=False),
        sa.Column("best_total", sa.Float(), nullable=False),
        sa.Column("last_stage", sa.String(length=16), nullable=False),
        sa.Column("last_session_id", sa.String(length=36), nullable=False),
        sa.Column("estimated_seconds", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id", "scene_id"),
    )


def downgrade() -> None:
    op.drop_table("course_progress")
    op.drop_index("ux_assessment_answers_attempt_question", table_name="assessment_answers")
    op.drop_index("ix_assessment_answers_attempt_id", table_name="assessment_answers")
    op.drop_table("assessment_answers")
    op.drop_index("ix_assessment_attempts_user_id", table_name="assessment_attempts")
    op.drop_table("assessment_attempts")
    op.drop_index("ix_generation_jobs_user_created", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_status", table_name="generation_jobs")
    op.drop_index("ix_generation_jobs_user_id", table_name="generation_jobs")
    op.drop_table("generation_jobs")
