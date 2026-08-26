"""add history book

按书隔离练习历史/进度: 多本书的 lesson_no 会重复 (business 第 1 课 vs
nce1 第 1 课), 历史行必须带 book 才能正确聚合. 存量行全部来自新概念,
默认 'nce1'.

Revision ID: a3f7c9d21b45
Revises: edb6eb8d27a1
Create Date: 2026-07-25 06:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3f7c9d21b45"
down_revision: str | None = "edb6eb8d27a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "history",
        sa.Column("book", sa.String(length=32), nullable=False, server_default="nce1"),
    )
    op.create_index("ix_history_book", "history", ["book"])


def downgrade() -> None:
    op.drop_index("ix_history_book", table_name="history")
    op.drop_column("history", "book")
