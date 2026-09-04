"""M2 迁移与 ORM 契约测试 (画像 + 表达库, 计划 §5.2 M2 / 阶段 P3).

与 ``test_practice_models.py`` (M1) 同一纪律: "模型 == 迁移 == 两种方言都建得出来"。

* 列契约: 画像 4 维**可空** (§5.6 门控的前提); 事件流水的 weight/source_kind 非空;
* ``(user_id, normalized)`` 唯一: 表达库去重的数据库级保证 (§5.7);
* ``ability_events(user_id, created_at)`` 复合索引: 轨迹查询的性能前提 (§5.2);
* 模型与迁移列集合零漂移; 整段 M2 升/降/重放的 sqlite 正反。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, select, text
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.schema import CreateTable

from app.config import settings
from app.models.db import (
    AbilityEvent,
    AbilityProfile,
    AnnotatedDiff,
    Expression,
    User,
)

M2_REVISION = "f3b8d0716c52"
M1_REVISION = "c9a1f4e7b208"
M2_TABLES = ("ability_profiles", "ability_events", "expressions", "annotated_diffs")
M1_TABLES = ("scene_courses", "practice_sessions", "practice_steps")
LEGACY_TABLES = ("users", "lessons", "history", "tts_cache")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "db" / "migrations"


# ------------------------------------------------------------------ 列契约


def test_ability_profile_column_contract() -> None:
    cols = {c.name: c for c in AbilityProfile.__table__.columns}
    assert set(cols) == {
        "user_id",
        "pronunciation",
        "grammar",
        "vocabulary",
        "fluency",
        "pronunciation_n",
        "grammar_n",
        "vocabulary_n",
        "fluency_n",
        "cefr_level",
        "assessment_cefr",
        "band_locked",
        "created_at",
        "updated_at",
    }
    # 4 维分可空: NULL = 没有被计入的证据 (§5.6); n / 锁带开关不许空.
    for dim in ("pronunciation", "grammar", "vocabulary", "fluency"):
        assert cols[dim].nullable, dim
    assert cols["user_id"].primary_key  # 一人一行画像
    assert not cols["band_locked"].nullable
    assert cols["cefr_level"].nullable and cols["assessment_cefr"].nullable  # 测评前 null


def test_ability_event_column_contract() -> None:
    cols = {c.name: c for c in AbilityEvent.__table__.columns}
    assert set(cols) == {
        "id",
        "user_id",
        "dimension",
        "score",
        "weight",
        "source_kind",
        "ise_ref_mode",
        "session_id",
        "step_id",
        "created_at",
    }
    assert not cols["score"].nullable and not cols["weight"].nullable
    assert not cols["source_kind"].nullable
    assert cols["ise_ref_mode"].nullable and cols["session_id"].nullable
    # 唯一的真外键是 user: session_id **无外键** (自由对话轮没有 practice_session,
    # 审计流水也不该被会话行的生命周期钉死).
    fk_targets = {
        (fk.column.table.name, fk.column.name) for fk in AbilityEvent.__table__.foreign_keys
    }
    assert fk_targets == {("users", "id")}


def test_event_and_expression_indexes() -> None:
    ev_indexes = {
        idx.name: [col.name for col in idx.columns] for idx in AbilityEvent.__table__.indexes
    }
    assert ev_indexes["ix_ability_events_user_created"] == ["user_id", "created_at"]
    expr_indexes = {
        idx.name: ([col.name for col in idx.columns], bool(idx.unique))
        for idx in Expression.__table__.indexes
    }
    assert expr_indexes["ix_expressions_user_normalized"] == (["user_id", "normalized"], True)
    diff_indexes = {idx.name for idx in AnnotatedDiff.__table__.indexes}
    assert "ix_annotated_diffs_user_id" in diff_indexes


def test_m2_tables_render_on_both_dialects() -> None:
    for model in (AbilityEvent, AbilityProfile, Expression, AnnotatedDiff):
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            assert model.__tablename__ in ddl


# ------------------------------------------------------------------ 行为契约


@pytest.mark.asyncio
async def test_expression_duplicate_is_rejected_per_user(db: AsyncSession) -> None:
    user = User(device_id="dev-expr")
    other = User(device_id="dev-expr-2")
    db.add_all([user, other])
    await db.flush()
    user_id, other_id = user.id, other.id  # rollback 后属性过期, 先抓成普通 str
    db.add(Expression(user_id=user_id, polished="How?", normalized="how"))
    await db.commit()
    db.add(Expression(user_id=user_id, polished="How?", normalized="how"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    db.add(Expression(user_id=other_id, polished="How?", normalized="how"))
    await db.commit()  # 去重是"每人每句", 不是全局
    rows = (await db.execute(select(Expression))).scalars().all()
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_event_and_profile_defaults(db: AsyncSession) -> None:
    user = User(device_id="dev-defaults")
    db.add(user)
    await db.flush()
    db.add(AbilityEvent(user_id=user.id, dimension="grammar", score=70.0, source_kind="llm"))
    db.add(AbilityProfile(user_id=user.id))
    await db.commit()
    event = (await db.execute(select(AbilityEvent))).scalar_one()
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert event.weight == 1.0 and event.step_id == "" and event.session_id is None
    assert event.ise_ref_mode is None
    assert profile.pronunciation is None and profile.pronunciation_n == 0
    assert profile.band_locked is False and profile.cefr_level is None
    assert profile.updated_at is not None


@pytest.mark.asyncio
async def test_same_second_events_do_not_merge(db: AsyncSession) -> None:
    """流水逐条落行: 同一用户同秒两条也必须 2 行 (PK 是独立 uuid)."""
    user = User(device_id="dev-two-rows")
    db.add(user)
    await db.flush()
    for score in (70.0, 90.0):
        db.add(AbilityEvent(user_id=user.id, dimension="grammar", score=score, source_kind="llm"))
    await db.commit()
    rows = (await db.execute(select(AbilityEvent))).scalars().all()
    assert len(rows) == 2 and len({r.id for r in rows}) == 2


# ------------------------------------------------------------------ 迁移正反


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def _prepare_m1(url: str) -> Config:
    """建出 M1/M2 之前的表并 stamp 到 M1 (绕开既有 int 链在 sqlite 的 batch-mode 坑)."""
    from app.db.base import Base

    cfg = _alembic_config()
    tables = [Base.metadata.tables[name] for name in LEGACY_TABLES + M1_TABLES]
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine, tables=tables)
    finally:
        engine.dispose()
    command.stamp(cfg, M1_REVISION)
    return cfg


def _inspect(url: str) -> tuple[set[str], dict[str, set[str]], set[str]]:
    engine = create_engine(url)
    try:
        insp = sa_inspect(engine)
        names = set(insp.get_table_names())
        columns = {t: {c["name"] for c in insp.get_columns(t)} for t in names}
        indexes = {i["name"] or "" for t in names for i in insp.get_indexes(t)}
        return names, columns, indexes
    finally:
        engine.dispose()


def _version(url: str) -> str:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return str(conn.execute(text("select version_num from alembic_version")).scalar_one())
    finally:
        engine.dispose()


def test_m2_upgrade_then_downgrade_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    url = f"sqlite:///{tmp_path / 'm2.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = _prepare_m1(url)
    before, _, _ = _inspect(url)
    assert set(M2_TABLES) & before == set()

    command.upgrade(cfg, "head")
    names, columns, indexes = _inspect(url)
    assert set(M2_TABLES) <= names
    assert _version(url) == M2_REVISION
    assert "weight" in columns["ability_events"]
    assert "ix_ability_events_user_created" in indexes
    assert "ix_expressions_user_normalized" in indexes

    command.downgrade(cfg, M1_REVISION)
    names_after, _, indexes_after = _inspect(url)
    assert not set(M2_TABLES) & names_after
    assert set(M1_TABLES) | set(LEGACY_TABLES) <= names_after
    assert "ix_expressions_user_normalized" not in indexes_after
    assert _version(url) == M1_REVISION

    command.upgrade(cfg, "head")  # 可重放
    assert set(M2_TABLES) <= _inspect(url)[0]


def test_m2_migration_matches_orm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    url = f"sqlite:///{tmp_path / 'm2_match.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = _prepare_m1(url)
    command.upgrade(cfg, "head")
    _, columns, _ = _inspect(url)
    for model in (AbilityEvent, AbilityProfile, Expression, AnnotatedDiff):
        expected = {c.name for c in model.__table__.columns}
        assert expected == columns[model.__tablename__], f"{model.__tablename__} 列漂移"


def test_m2_is_the_only_head_and_chains_from_m1() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [M2_REVISION]
    assert script.get_revision(M2_REVISION).down_revision == M1_REVISION
