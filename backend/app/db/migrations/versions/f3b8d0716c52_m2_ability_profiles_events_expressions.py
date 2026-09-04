"""M2: ability_profiles + ability_events + expressions + annotated_diffs

v2.0 计划 §5.2 M2 —— 能力画像与表达库, 全部 add-only (不动 M1 与既有表):

* ``ability_events``    **流水是唯一事实来源**: 每次有分尝试 x 维度一行, 含被门控的
  (weight=0) 证据; (user_id, created_at) 索引支撑轨迹聚合与整表重放。
  ``session_id`` 刻意**不加外键** —— 自由对话轮没有 practice_session, 审计流水也
  不该被会话行的生命周期钉死。
* ``ability_profiles``  events 的**可重建物化快照** (§5.2): user_id 主键, 4 维分
  可空 (NULL = 没有被计入的证据) + 各维 n 计数 + CEFR/band_locked 锁带字段。
* ``expressions``       个人表达库 (§5.7), (user_id, normalized) 唯一索引做去重。
* ``annotated_diffs``   §5.2 里排在 M4 的润色对照流水, 因复盘报告 (P3) 就需要它,
  随 M2 一并落地 (T4); M4 只剩 drop tts_cache。

JSON/日期列沿用 M1 口径: 只用到 sqlite 与 PG16 都渲得出的类型。

Revision ID: f3b8d0716c52
Revises: c9a1f4e7b208
Create Date: 2026-09-05 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3b8d0716c52"
down_revision: str | None = "c9a1f4e7b208"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ability_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("dimension", sa.String(length=16), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        # 0 = 被门控 (stub/heuristic/skip), 画像不动.
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("source_kind", sa.String(length=16), nullable=False),
        sa.Column("ise_ref_mode", sa.String(length=32), nullable=True),
        # 无外键: 自由对话轮没有 practice_session 可指 (见模块 docstring).
        sa.Column("session_id", sa.String(length=36), nullable=True),
        sa.Column("step_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ability_events_user_id", "ability_events", ["user_id"], unique=False)
    # 轨迹视图/画像重建: 某用户某时间段的全部证据.
    op.create_index("ix_ability_events_user_created", "ability_events", ["user_id", "created_at"])

    op.create_table(
        "ability_profiles",
        # user_id 直接做主键: 一人一行画像 (物化快照, 可整表重放).
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("pronunciation", sa.Float(), nullable=True),
        sa.Column("grammar", sa.Float(), nullable=True),
        sa.Column("vocabulary", sa.Float(), nullable=True),
        sa.Column("fluency", sa.Float(), nullable=True),
        sa.Column("pronunciation_n", sa.Integer(), nullable=False),
        sa.Column("grammar_n", sa.Integer(), nullable=False),
        sa.Column("vocabulary_n", sa.Integer(), nullable=False),
        sa.Column("fluency_n", sa.Integer(), nullable=False),
        sa.Column("cefr_level", sa.String(length=8), nullable=True),
        sa.Column("assessment_cefr", sa.String(length=8), nullable=True),
        sa.Column("band_locked", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )

    op.create_table(
        "expressions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("polished", sa.Text(), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("explanation_cn", sa.Text(), nullable=False),
        sa.Column("source_label", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("normalized", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_expressions_user_id", "expressions", ["user_id"], unique=False)
    # §5.7: user 维度按归一化润色句去重.
    op.create_index(
        "ix_expressions_user_normalized",
        "expressions",
        ["user_id", "normalized"],
        unique=True,
    )

    op.create_table(
        "annotated_diffs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("original", sa.Text(), nullable=False),
        sa.Column("polished", sa.Text(), nullable=False),
        sa.Column("explanation_cn", sa.Text(), nullable=False),
        sa.Column("origin", sa.String(length=32), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("step_id", sa.String(length=32), nullable=False),
        sa.Column("scene_id", sa.String(length=64), nullable=False),
        sa.Column("llm_source", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_annotated_diffs_user_id", "annotated_diffs", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_annotated_diffs_user_id", table_name="annotated_diffs")
    op.drop_table("annotated_diffs")
    op.drop_index("ix_expressions_user_normalized", table_name="expressions")
    op.drop_index("ix_expressions_user_id", table_name="expressions")
    op.drop_table("expressions")
    op.drop_table("ability_profiles")
    op.drop_index("ix_ability_events_user_created", table_name="ability_events")
    op.drop_index("ix_ability_events_user_id", table_name="ability_events")
    op.drop_table("ability_events")
