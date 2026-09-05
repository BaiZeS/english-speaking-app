"""Alembic 整链在 sqlite 上必须可从零升到 head (P8/T9 回归测试).

背景: v2.0 期间所有新库都靠 ``Base.metadata.create_all`` (conftest), 只有
真实部署 (和这里) 会走完整迁移链 —— ``edb6eb8d27a1`` 的 ``op.drop_constraint``
在 sqlite 上直接抛 NotSupportedError, 空库永远升不到 head (计划 §P8 第 1 项).

测试刻意用**文件型 sqlite** (而非 :memory:): batch_alter_table 的
copy-and-recreate 需要跨语句看到同一张表, 内存库每个连接都是新库会假绿。
PG16 链路 (``op.drop_constraint`` 直删) 由 CI 的 postgres 服务跑同样端点覆盖;
本测试钉的是 sqlite 半边。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

from app.config import settings

PROJECT_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_TABLES = {
    "users",
    "lessons",
    "history",
    "tts_cache",
    "scene_courses",
    "practice_sessions",
    "practice_steps",
    "ability_profiles",
    "ability_events",
    "expressions",
    "annotated_diffs",
    "generation_jobs",
    "assessment_attempts",
    "assessment_answers",
    "course_progress",
    "alembic_version",
}


def _alembic_config(database_url: str, monkeypatch: pytest.MonkeyPatch) -> Config:
    # migrations/env.py 读 settings.database_url (模块 import 时求值), 直接
    # monkeypatch 单例即可, 不需要子进程环境变量。
    monkeypatch.setattr(settings, "database_url", database_url)
    cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(PROJECT_ROOT / "app" / "db" / "migrations"))
    return cfg


def _table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("select name from sqlite_master where type='table'")
        return {row[0] for row in rows}


def _history_fks(db_path: Path) -> list[tuple[str, str]]:
    """(from_column, to_table) pairs of the FKs currently on ``history``.

    PRAGMA foreign_key_list 的列序是 (id, seq, table, from, to, ...) ——
    ``row[3]`` 是本表列, ``row[2]`` 是引用表, 别弄反了。
    """
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute("PRAGMA foreign_key_list('history')")
        return [(row[3], row[2]) for row in rows]


def test_sqlite_fresh_database_upgrades_to_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "fresh.db"
    cfg = _alembic_config(f"sqlite:///{db}", monkeypatch)

    command.upgrade(cfg, "head")

    tables = _table_names(db)
    assert tables >= EXPECTED_TABLES, f"missing: {EXPECTED_TABLES - tables}"
    # edb6eb8d27a1 的效果: lesson_id 外键没了, user_id 外键还在。
    assert ("lesson_id", "lessons") not in _history_fks(db)
    assert ("user_id", "users") in _history_fks(db)

    # 单步回退 (head -> M3 之前) 再把整链升回来。
    command.downgrade(cfg, "-1")
    command.upgrade(cfg, "head")
    assert _table_names(db) >= EXPECTED_TABLES

    # 全链回 base 再回 head: 双向可逆, 且 drop history 表的初代迁移也能跑。
    command.downgrade(cfg, "base")
    assert "history" not in _table_names(db)
    command.upgrade(cfg, "head")
    assert _table_names(db) >= EXPECTED_TABLES


def test_sqlite_fk_downgrade_recreates_constraint_and_keeps_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """edb6eb8d27a1 的 downgrade 单独验: batch 重建必须保留数据 + 恢复 FK."""
    db = tmp_path / "chain.db"
    cfg = _alembic_config(f"sqlite:///{db}", monkeypatch)
    command.upgrade(cfg, "head")

    with sqlite3.connect(db) as conn:
        conn.execute("pragma foreign_keys = off")
        conn.execute(
            "insert into history (id, user_id, book, lesson_id, line_id, audio_path,"
            " score_total, score_pronunciation, score_fluency, score_completeness,"
            " created_at) values ('h1','u1','nce1',7,'L1','a.wav',80,80,80,80,"
            " '2026-01-01 00:00:00')"
        )
        conn.commit()

    command.downgrade(cfg, "d5ccd34b98e6")  # 走过 edb6eb8d27a1 的 downgrade
    fks = _history_fks(db)
    assert ("lesson_id", "lessons") in fks, f"lesson FK not recreated: {fks}"
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from history").fetchone()[0] == 1

    command.upgrade(cfg, "head")
    assert ("lesson_id", "lessons") not in _history_fks(db)
