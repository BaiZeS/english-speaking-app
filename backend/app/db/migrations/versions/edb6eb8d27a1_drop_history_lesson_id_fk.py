"""drop history lesson_id fk

Revision ID: edb6eb8d27a1
Revises: d5ccd34b98e6
Create Date: 2026-07-12 05:05:48.243664
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "edb6eb8d27a1"
down_revision: str | None = "d5ccd34b98e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("history_lesson_id_fkey", "history", type_="foreignkey")


def downgrade() -> None:
    op.create_foreign_key("history_lesson_id_fkey", "history", "lessons", ["lesson_id"], ["id"])
