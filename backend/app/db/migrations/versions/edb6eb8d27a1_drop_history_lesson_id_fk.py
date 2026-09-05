"""drop history lesson_id fk

Revision ID: edb6eb8d27a1
Revises: d5ccd34b98e6
Create Date: 2026-07-12 05:05:48.243664
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "edb6eb8d27a1"
down_revision: str | None = "d5ccd34b98e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


#: FK 在 init 迁移里没有显式命名; sqlite batch 模式需要一个**合成名**来定位待删除
#: 的约束 (alembic "Using Batch with Foreign Keys" 的推荐做法)。PG 上这条约束的
#: 实际名字是 ``history_lesson_id_fkey`` (PG 默认命名约定)。
_SQLITE_NAMING = {"fk": "fk_%(table_name)s_%(column_0_name)s"}
_SQLITE_SYNTHETIC_FK_NAME = "fk_history_lesson_id"


def _sqlite_lesson_fk_name() -> str:
    """反射当前库上 lesson_id FK 的名字.

    初代库里这条 FK 是匿名的 (反射 -> None -> 用 naming_convention 合成名定位);
    而本迁移的 downgrade 在 sqlite 上重建时用了显式名 ``history_lesson_id_fkey``
    —— 回退再前滚的链路必须按真实名字来删, 否则 batch 报 No such constraint。
    """
    insp = sa.inspect(op.get_bind())
    for fk in insp.get_foreign_keys("history"):
        if list(fk.get("constrained_columns") or []) == ["lesson_id"]:
            name = fk.get("name")
            if isinstance(name, str) and name:
                return name
            break
    return _SQLITE_SYNTHETIC_FK_NAME


def upgrade() -> None:
    # SQLite 不支持 ALTER TABLE DROP CONSTRAINT, 走 batch (copy-and-recreate) 模式;
    # PG 保持直接 DROP。(P8 修复: 旧写法在 sqlite 整链 upgrade 时抛
    # NotSupportedError, 空库无法从零升到 head —— 见 tests/test_migrations_sqlite.py。)
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("history", naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.drop_constraint(_sqlite_lesson_fk_name(), type_="foreignkey")
    else:
        op.drop_constraint("history_lesson_id_fkey", "history", type_="foreignkey")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        with op.batch_alter_table("history", naming_convention=_SQLITE_NAMING) as batch_op:
            batch_op.create_foreign_key("history_lesson_id_fkey", "lessons", ["lesson_id"], ["id"])
    else:
        op.create_foreign_key("history_lesson_id_fkey", "history", "lessons", ["lesson_id"], ["id"])
