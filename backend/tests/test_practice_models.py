"""M1 迁移与 ORM 模型的契约测试 (计划 §5.2 M1).

钉住三张新表 (``scene_courses`` / ``practice_sessions`` / ``practice_steps``) 的
"模型 == 迁移 == 两种方言都建得出来" 这层关系:

* **列名集合**: 端点与 P3/P4 的读路径按列名取数, 悄悄改名 = 运行期才炸.
* **分数列必须可空**: §5.6 画像门控的前提是"这个维度本次没有证据" != 0 分.
* ``(user_id, status, last_active_at DESC)`` 复合索引: 首页「继续学习」的性能前提,
  也是计划 §5.2 点名的索引 (排序方向按渲染出的 DDL 断言).
* ``revision`` 是 SQLAlchemy 的 version_id_col —— doc 乐观锁; 并发 ``/step`` 不双推进
  的另一半证据在 ``test_course_sessions.py``.
* M1 在 sqlite 上升->降->再升真跑一遍 (PG16 上同样跑过, 见 tasks/T3/progress.md).
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
from sqlalchemy.schema import CreateIndex, CreateTable

from app.config import settings
from app.models.db import (
    AbilityEvent,
    AbilityProfile,
    AnnotatedDiff,
    AssessmentAnswer,
    AssessmentAttempt,
    CourseProgressRow,
    Expression,
    GenerationJob,
    PracticeSession,
    PracticeStep,
    SceneCourseRow,
    User,
)

M1_REVISION = "c9a1f4e7b208"
PREVIOUS_REVISION = "a3f7c9d21b45"
M1_TABLES = ("scene_courses", "practice_sessions", "practice_steps")
# P3/T4 的 M2 (能力画像 + 表达库) 续在 M1 后面; T5 的 M3 还会再续.
M2_REVISION = "f3b8d0716c52"
M2_TABLES = ("ability_profiles", "ability_events", "expressions", "annotated_diffs")
# T5 的 M3 (生成任务 + 测评 + 通关进度) 续在 M2 后面 (contracts 在 test_m3_models.py).
M3_REVISION = "9d2e4c6a8f01"
M3_TABLES = ("generation_jobs", "assessment_attempts", "assessment_answers", "course_progress")
LEGACY_TABLES = ("users", "lessons", "history", "tts_cache")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "db" / "migrations"


# ------------------------------------------------------------------ 列契约


def test_scene_courses_columns() -> None:
    cols = {c.name: c for c in SceneCourseRow.__table__.columns}
    assert {
        "id",
        "user_id",
        "scene_key",
        "doc",
        "status",
        "created_at",
        "updated_at",
    } <= set(cols)
    # 生成课整份内容进 doc (P4 写), 状态单独成列便于画廊过滤
    assert type(cols["doc"].type).__name__ == "JSON"
    assert not cols["doc"].nullable


def test_practice_sessions_columns() -> None:
    cols = {c.name: c for c in PracticeSession.__table__.columns}
    assert {
        "id",
        "user_id",
        "kind",
        "scene_id",
        "stage",
        "status",
        "doc",
        "revision",
        "owner_device_id",
        "last_active_at",
        "created_at",
        "updated_at",
    } <= set(cols)


def test_practice_steps_score_columns_are_nullable() -> None:
    """六个分数列 + 派生指标**全部可空**: NULL = 该维度本次没有证据 (§5.6)."""
    cols = {c.name: c for c in PracticeStep.__table__.columns}
    scores = (
        "score_total",
        "score_pronunciation",
        "score_fluency",
        "score_completeness",
        "score_grammar",
        "score_vocabulary",
    )
    for name in (*scores, "transcript", "ise_ref_mode", "annotated_json", "speech_rate_wpm"):
        assert cols[name].nullable, name
    assert all(name in cols for name in scores)
    # provenance 与 ok 是每行都有的事实, 不允许空
    assert not cols["source"].nullable
    assert not cols["ok"].nullable


def test_json_columns_render_on_both_dialects() -> None:
    """JSON 列在 sqlite (测试) 与 PG16 (生产) 上都渲得出来 (§5.2 的硬要求)."""
    for model in (PracticeSession, PracticeStep, SceneCourseRow):
        sqlite_ddl = str(CreateTable(model.__table__).compile(dialect=sqlite.dialect()))
        pg_ddl = str(CreateTable(model.__table__).compile(dialect=postgresql.dialect()))
        assert "JSON" in sqlite_ddl and "JSON" in pg_ddl, model.__tablename__
        assert "JSONB" not in pg_ddl, "v2.0 统一用 sqlalchemy.JSON, 不用 PG 专属 JSONB"


def test_recency_index_ddl_is_descending_on_both_dialects() -> None:
    """计划点名的 ``(user_id, status, last_active_at DESC)`` 索引, 两个方言都得带 DESC."""
    index = next(
        idx
        for idx in PracticeSession.__table__.indexes
        if idx.name == "ix_practice_sessions_user_status_recency"
    )
    for dialect in (sqlite.dialect(), postgresql.dialect()):
        ddl = str(CreateIndex(index).compile(dialect=dialect))
        assert "user_id" in ddl and "status" in ddl, ddl
        assert "last_active_at DESC" in ddl, ddl


def test_scene_courses_and_steps_extra_indexes() -> None:
    step_indexes = {
        idx.name: [c.name for c in idx.columns] for idx in PracticeStep.__table__.indexes
    }
    assert step_indexes["ix_practice_steps_session_step"] == ["session_id", "step_index"]
    course_indexes = {
        idx.name: ([c.name for c in idx.columns], bool(idx.unique))
        for idx in SceneCourseRow.__table__.indexes
    }
    assert course_indexes["ix_scene_courses_user_scene_key"] == (["user_id", "scene_key"], True)
    session_indexes = {
        idx.name: [c.name for c in idx.columns] for idx in PracticeSession.__table__.indexes
    }
    assert session_indexes["ix_practice_sessions_user_scene"] == ["user_id", "scene_id"]


# ------------------------------------------------------------------ 行为契约


@pytest.mark.asyncio
async def test_session_revision_is_optimistic_version_column(db: AsyncSession) -> None:
    """``revision`` 由 version_id_col 维护: INSERT=1, 每次成功 UPDATE +1."""
    user = User(device_id="dev-rev")
    db.add(user)
    await db.flush()
    row = PracticeSession(user_id=user.id, scene_id="scene_x", doc={"v": 1})
    db.add(row)
    await db.commit()
    assert row.revision == 1
    assert (row.stage, row.status, row.kind) == ("briefing", "active", "scene_course")

    row.doc = {"v": 2}
    await db.commit()
    assert row.revision == 2


@pytest.mark.asyncio
async def test_doc_column_needs_whole_object_reassignment(db: AsyncSession) -> None:
    """把 JSON 写入契约钉成测试: 原地改 ``row.doc`` 不会被 UPDATE.

    这正是 ``course_sessions._doc_of`` 必须深拷贝的理由 —— 以后谁想"省一次拷贝"把它
    优化掉, 这条测试会立刻告诉他会话进度会静默丢失.
    """
    user = User(device_id="dev-doc")
    db.add(user)
    await db.flush()
    row = PracticeSession(user_id=user.id, scene_id="scene_x", doc={"steps": []})
    db.add(row)
    await db.commit()

    row.doc["steps"] = [{"id": "f1"}]  # 原地改: 变更历史是空的
    await db.commit()
    assert (await _reload(db, row.id)).doc == {"steps": []}

    fresh = await _reload(db, row.id)
    fresh.doc = {"steps": [{"id": "f1"}]}  # 整体换对象才有效
    await db.commit()
    assert (await _reload(db, row.id)).doc == {"steps": [{"id": "f1"}]}


async def _reload(db: AsyncSession, session_id: str) -> PracticeSession:
    """绕开身份映射读真值 (否则拿到的是内存里那份)."""
    res = await db.execute(
        select(PracticeSession)
        .where(PracticeSession.id == session_id)
        .execution_options(populate_existing=True)
    )
    return res.scalar_one()


@pytest.mark.asyncio
async def test_step_row_accepts_all_null_scores_for_a_skip(db: AsyncSession) -> None:
    """跳过 = 一行没有分数、但有 ``source="skip"`` + ``ok=True`` 的证据 (P2 口径)."""
    user = User(device_id="dev-skip")
    db.add(user)
    await db.flush()
    sess = PracticeSession(user_id=user.id, scene_id="scene_x", doc={"v": 1})
    db.add(sess)
    await db.flush()
    step = PracticeStep(
        session_id=sess.id,
        user_id=user.id,
        step_id="f1",
        step_type="read_along",
        source="skip",
        ok=True,
    )
    db.add(step)
    await db.commit()
    got = (await db.execute(select(PracticeStep).where(PracticeStep.id == step.id))).scalar_one()
    assert got.score_total is None and got.ise_ref_mode is None and got.llm_source is None
    assert got.ok is True and got.source == "skip" and got.attempt == 1


@pytest.mark.asyncio
async def test_scene_course_duplicate_key_is_rejected_per_user(db: AsyncSession) -> None:
    """``(user_id, scene_key)`` 唯一: 同一目标重复生成应 upsert 而不是堆行 (P4 前提)."""
    user = User(device_id="dev-uniq")
    db.add(user)
    await db.flush()
    db.add(SceneCourseRow(user_id=user.id, scene_key="goal-1", doc={"id": "scene_x"}))
    await db.commit()
    db.add(SceneCourseRow(user_id=user.id, scene_key="goal-1", doc={"id": "scene_y"}))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()
    # 去重是"每人每目标", 不是全局: 另一个用户同 key 照收
    other = User(device_id="dev-uniq-2")
    db.add(other)
    await db.flush()
    db.add(SceneCourseRow(user_id=other.id, scene_key="goal-1", doc={"id": "scene_z"}))
    await db.commit()
    rows = (await db.execute(select(SceneCourseRow))).scalars().all()
    assert len(rows) == 2


# ------------------------------------------------------------------ 迁移正反


def _alembic_config() -> Config:
    """不读 alembic.ini 的 Config: ``env.py`` 自己从 ``settings.database_url`` 取 URL."""
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def _create_legacy_tables(url: str) -> None:
    """只建 M1 之前的既有表 (整链在 sqlite 上跑不动, 见下面的说明)."""
    from app.db.base import Base

    legacy = [Base.metadata.tables[name] for name in LEGACY_TABLES]
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine, tables=legacy)
    finally:
        engine.dispose()


def _inspect(url: str) -> tuple[set[str], dict[str, set[str]], set[str]]:
    """(表名, 表->列名, 索引名). 用同步引擎看, 与迁移同一套驱动口径."""
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


def test_m1_then_m2_upgrade_downgrade_on_sqlite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """M1 升 -> M2 升 -> 逐段降 -> 重放, 全在 sqlite 上正反跑.

    链条从 0 开始跑不动 sqlite: 既有迁移 ``edb6eb8d27a1`` 用 ``op.drop_constraint``
    删 history 外键, sqlite 不支持 (要 batch mode)。那是 **P2 之前的既有限制** —— CI 与
    生产都在 PG16 上跑整链 (M1/M2 也在 PG 上正反验过, 见 tasks/T3+T4 progress.md)。这里
    先建出既有表 + stamp 到前一个 head, 把 **M1/M2 这两步** 在 sqlite 上正反跑一遍。
    """
    url = f"sqlite:///{tmp_path / 'm1.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = _alembic_config()
    _create_legacy_tables(url)
    command.stamp(cfg, PREVIOUS_REVISION)

    command.upgrade(cfg, M1_REVISION)
    names, columns, indexes = _inspect(url)
    assert set(M1_TABLES) <= names
    assert _version(url) == M1_REVISION
    assert "revision" in columns["practice_sessions"]
    assert "ix_practice_sessions_user_status_recency" in indexes
    assert not set(M2_TABLES) & names  # M2 还没上来

    command.upgrade(cfg, "head")  # M2 + (T5 的) M3 一起上来
    names, columns, indexes = _inspect(url)
    assert set(M2_TABLES) | set(M3_TABLES) <= names
    assert _version(url) == M3_REVISION
    assert "ix_ability_events_user_created" in indexes
    assert "ix_expressions_user_normalized" in indexes

    command.downgrade(cfg, M1_REVISION)  # 退掉 M2+M3
    names_after, _, indexes_after = _inspect(url)
    assert not set(M2_TABLES) & names_after
    assert not set(M3_TABLES) & names_after
    assert set(M1_TABLES) <= names_after  # M1 原样在
    assert "ix_ability_events_user_created" not in indexes_after
    assert _version(url) == M1_REVISION

    command.downgrade(cfg, PREVIOUS_REVISION)  # 再退 M1
    names_after, _, indexes_after = _inspect(url)
    assert not set(M1_TABLES) & names_after
    assert set(LEGACY_TABLES) <= names_after  # 老表一支没动
    assert "ix_practice_sessions_user_status_recency" not in indexes_after
    assert _version(url) == PREVIOUS_REVISION

    command.upgrade(cfg, "head")  # 整段可重放 (M3 续链后同样成立)
    assert set(M1_TABLES) | set(M2_TABLES) | set(M3_TABLES) <= _inspect(url)[0]


def test_migrations_match_orm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """迁移建出来的列集合必须与 ORM 一致 (漏列 = 运行期才炸的定时炸弹).

    M1 (T3) 与 M2 (T4) 的全部新表都进来对 —— 这是 ``alembic check`` 的 sqlite 版,
    PG16 上的真 ``alembic check`` 见 tasks/T4/progress.md.
    """
    url = f"sqlite:///{tmp_path / 'm1_match.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    _create_legacy_tables(url)
    cfg = _alembic_config()
    command.stamp(cfg, PREVIOUS_REVISION)
    command.upgrade(cfg, "head")
    _, columns, _ = _inspect(url)
    for model in (
        PracticeSession,
        PracticeStep,
        SceneCourseRow,
        AbilityProfile,
        AbilityEvent,
        Expression,
        AnnotatedDiff,
        GenerationJob,
        AssessmentAttempt,
        AssessmentAnswer,
        CourseProgressRow,
    ):
        expected = {c.name for c in model.__table__.columns}
        assert expected == columns[model.__tablename__], (
            f"{model.__tablename__} 列漂移: {expected ^ columns[model.__tablename__]}"
        )


def test_single_head_chains_m1_then_m2() -> None:
    """单 head + 挂链正确: M3(T5) 修 M2(T4), M2 修 M1(T3), M1 修 P1-era head."""
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [M3_REVISION]
    assert script.get_revision(M3_REVISION).down_revision == M2_REVISION
    assert script.get_revision(M2_REVISION).down_revision == M1_REVISION
    assert script.get_revision(M1_REVISION).down_revision == PREVIOUS_REVISION
