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

#: T4 新增的那个 revision (dialogue_scenes + generation_jobs.kind); 它必须接在
#: T4 动手时的 head ``9d2e4c6a8f01`` 之后, 且是当前唯一 head。
T4_REVISION = "c3b7e5a91d24"

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
    "dialogue_scenes",
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


def _table_columns(db_path: Path, table: str) -> dict[str, tuple[str, str]]:
    """(列名 -> (类型, dflt_value)) —— PRAGMA table_info 的 name/type/dflt_value."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(f"PRAGMA table_info('{table}')")
        return {str(row[1]): (str(row[2]), str(row[4] or "")) for row in rows}


def _unique_indexes(db_path: Path, table: str) -> set[tuple[str, ...]]:
    """该表上的唯一索引列组合 (sqlite_master 的 index SQL 里挑 unique 的那些)."""
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "select name, sql from sqlite_master where type='index' and tbl_name=?",
            (table,),
        )
        unique: set[tuple[str, ...]] = set()
        for name, sql in rows:
            if not sql or "UNIQUE" not in str(sql).upper():
                continue
            cols: list[str] = []
            for info in conn.execute(f"PRAGMA index_info('{name}')"):
                cols.append(str(info[2]))
            unique.add(tuple(cols))
        return unique


def test_alembic_head_is_the_t4_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    """链条必须仍是**单线**, 且 T4 的 revision 挂在当时的 head 上 (§3 C1 的硬要求).

    计划原文: ``down_revision = "9d2e4c6a8f01"`` (T4 动手时的 head)。这条不写死父节点
    字符串去对, 而是问 ScriptDirectory 要真值: head 只要不是这一个 (有人插了分支 /
    改了父节点 / 又叠了迁移却没改本用例) 就红 —— 顺便钉住"新 revision 真的接进去了"。
    """
    from alembic.script import ScriptDirectory

    cfg = _alembic_config("sqlite://", monkeypatch)
    script = ScriptDirectory.from_config(cfg)
    assert script.get_heads() == [T4_REVISION], f"heads={script.get_heads()}"
    assert script.get_revision(T4_REVISION).down_revision == "9d2e4c6a8f01"


def test_sqlite_new_dialogue_scene_table_and_job_kind_column(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """T4 这一个 revision 自己的升级/回退 (不依赖整链重建, 见上面那条的 edb6 注记).

    * ``dialogue_scenes`` 建出来, ``(user_id, scene_key)`` 是唯一索引 (upsert 幂等的前提);
    * ``generation_jobs.kind`` 加上来且有 ``server_default='course'`` (旧行回填的载体);
    * 回退一步: 表没了、列没了 —— 双向可逆。
    """
    db = tmp_path / "t4.db"
    cfg = _alembic_config(f"sqlite:///{db}", monkeypatch)
    command.upgrade(cfg, "head")

    assert "dialogue_scenes" in _table_names(db)
    index_cols = _unique_indexes(db, "dialogue_scenes")
    assert ("user_id", "scene_key") in index_cols, index_cols
    kind = _table_columns(db, "generation_jobs").get("kind")
    assert kind is not None and kind[0].upper() == "VARCHAR(32)"
    assert "course" in kind[1], f"kind 的 server_default 丢了: {kind}"

    command.downgrade(cfg, "-1")
    assert "dialogue_scenes" not in _table_names(db)
    assert "kind" not in _table_columns(db, "generation_jobs")

    command.upgrade(cfg, "head")
    assert "dialogue_scenes" in _table_names(db)
    assert "kind" in _table_columns(db, "generation_jobs")


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
