"""M3 迁移与 ORM 的契约测试 (计划 §5.2 M3, T5).

钉住四张新表 (``generation_jobs`` / ``assessment_attempts`` / ``assessment_answers``
/ ``course_progress``) 的「模型 == 迁移 == 两种方言都建得出来」这层关系; 行为契约
(生成 job 状态机 / 测评 / 进度 upsert) 分别在 ``test_course_generator`` /
``test_assessment`` / ``test_course_progress``。
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
    AssessmentAnswer,
    AssessmentAttempt,
    CourseProgressRow,
    GenerationJob,
    User,
)
from app.services.course_progress import record_finished_session

M2_REVISION = "f3b8d0716c52"
M3_REVISION = "9d2e4c6a8f01"
M2_TABLES = ("ability_profiles", "ability_events", "expressions", "annotated_diffs")
M3_TABLES = ("generation_jobs", "assessment_attempts", "assessment_answers", "course_progress")
LEGACY_TABLES = ("users", "lessons", "history", "tts_cache")
MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "app" / "db" / "migrations"


# ------------------------------------------------------------------ 列契约


def test_generation_jobs_columns() -> None:
    cols = {c.name: c for c in GenerationJob.__table__.columns}
    assert {
        "id",
        "user_id",
        "goal_text",
        "category",
        "level",
        "status",
        "progress",
        "stage_text",
        "scene_id",
        "error",
        "created_at",
        "updated_at",
    } <= set(cols)
    assert cols["error"].nullable  # 只有 failed 才有失败原因 (诚实给到客户端)
    assert cols["status"].default.arg == "running"
    assert cols["progress"].default.arg == 0.0


def test_assessment_columns() -> None:
    attempt = {c.name: c for c in AssessmentAttempt.__table__.columns}
    assert {"id", "user_id", "status", "answers_count", "result", "started_at", "finished_at"} <= (
        set(attempt)
    )
    assert attempt["result"].nullable  # running 时还没有结果
    assert type(attempt["result"].type).__name__ == "JSON"
    assert attempt["finished_at"].nullable
    answer = {c.name: c for c in AssessmentAnswer.__table__.columns}
    # 发音分只存真实 ISE: 列必须可空 (没配凭据时整行没有分数).
    assert answer["ise_score"].nullable and answer["speech_rate_wpm"].nullable
    unique = {idx.name: [c.name for c in idx.columns] for idx in AssessmentAnswer.__table__.indexes}
    assert unique["ux_assessment_answers_attempt_question"] == ["attempt_id", "question_no"]


def test_course_progress_composite_pk() -> None:
    table = CourseProgressRow.__table__
    assert [c.name for c in table.primary_key.columns] == ["user_id", "scene_id"]
    cols = {c.name: c for c in table.columns}
    assert not cols["cleared"].nullable and not cols["best_total"].nullable
    for name in ("attempts", "last_stage", "last_session_id", "estimated_seconds"):
        assert name in cols


def test_m3_json_column_renders_on_both_dialects() -> None:
    """``assessment_attempts.result`` 用 sqlalchemy.JSON (§5.2: sqlite/PG16 双通)."""
    for model in (AssessmentAttempt,):
        for dialect in (sqlite.dialect(), postgresql.dialect()):
            ddl = str(CreateTable(model.__table__).compile(dialect=dialect))
            assert "JSON" in ddl
    pg_ddl = str(CreateTable(AssessmentAttempt.__table__).compile(dialect=postgresql.dialect()))
    assert "JSONB" not in pg_ddl


def test_generation_jobs_user_recency_index() -> None:
    indexes = {idx.name: [c.name for c in idx.columns] for idx in GenerationJob.__table__.indexes}
    assert indexes["ix_generation_jobs_user_created"] == ["user_id", "created_at"]


# ------------------------------------------------------------------ 行为契约


@pytest.mark.asyncio
async def test_assessment_answer_unique_per_question(db: AsyncSession) -> None:
    """重答是覆盖不是堆行: (attempt_id, question_no) 唯一索引兜底."""
    user = User(device_id="dev-a1")
    db.add(user)
    await db.flush()
    attempt = AssessmentAttempt(user_id=user.id)
    db.add(attempt)
    await db.flush()
    db.add(AssessmentAnswer(attempt_id=attempt.id, question_no=1, transcript="first"))
    await db.commit()
    db.add(AssessmentAnswer(attempt_id=attempt.id, question_no=1, transcript="second"))
    with pytest.raises(IntegrityError):
        await db.commit()
    await db.rollback()


@pytest.mark.asyncio
async def test_generation_job_defaults(db: AsyncSession) -> None:
    user = User(device_id="dev-job")
    db.add(user)
    await db.flush()
    job = GenerationJob(user_id=user.id, goal_text="生成一门点咖啡的课")
    db.add(job)
    await db.commit()
    assert (job.status, job.progress, job.stage_text, job.scene_id) == ("running", 0.0, "", "")
    assert job.error is None


@pytest.mark.asyncio
async def test_course_progress_upsert_is_dialect_native(db: AsyncSession) -> None:
    """写侧走 ON CONFLICT: 同 (user, scene) 第二次收工是 UPDATE, 行数恒 1."""
    user = User(device_id="dev-cp")
    db.add(user)
    await db.flush()
    await record_finished_session(
        db,
        user_id=user.id,
        scene_id="scene_x",
        session_id="s1",
        cleared=False,
        best_total=66.0,
        last_stage="review",
        session_seconds=120.0,
    )
    await record_finished_session(
        db,
        user_id=user.id,
        scene_id="scene_x",
        session_id="s2",
        cleared=True,
        best_total=50.0,  # 更低 -> best_total 单调不回退
        last_stage="review",
        session_seconds=30.0,
    )
    await db.commit()
    rows = (
        (await db.execute(select(CourseProgressRow).where(CourseProgressRow.user_id == user.id)))
        .scalars()
        .all()
    )
    assert len(rows) == 1
    row = rows[0]
    assert (row.attempts, row.cleared) == (2, True)
    assert row.best_total == 66.0
    assert row.estimated_seconds == 150.0
    assert row.last_session_id == "s2"


# ------------------------------------------------------------------ 迁移正反


def _alembic_config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    return cfg


def _create_legacy_tables(url: str) -> None:
    from app.db.base import Base

    legacy = [Base.metadata.tables[name] for name in LEGACY_TABLES]
    engine = create_engine(url)
    try:
        Base.metadata.create_all(engine, tables=legacy)
    finally:
        engine.dispose()


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


def test_m3_upgrade_downgrade_on_sqlite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """从 P1-era head 一次升到 M3, 再退回 M2 -> 表干净消失 -> 重放 (sqlite 段)."""
    url = f"sqlite:///{tmp_path / 'm3.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    cfg = _alembic_config()
    _create_legacy_tables(url)
    command.stamp(cfg, "a3f7c9d21b45")  # P1-era head (sqlite 链限制同 T3/T4 说明)

    command.upgrade(cfg, "head")
    names, columns, indexes = _inspect(url)
    assert set(M2_TABLES) | set(M3_TABLES) <= names
    assert _version(url) == M3_REVISION
    assert "ux_assessment_answers_attempt_question" in indexes
    assert "error" in columns["generation_jobs"]
    assert "estimated_seconds" in columns["course_progress"]

    command.downgrade(cfg, M2_REVISION)  # 只退 M3
    names_after, _, _ = _inspect(url)
    assert not set(M3_TABLES) & names_after
    assert set(M2_TABLES) <= names_after
    assert _version(url) == M2_REVISION

    command.upgrade(cfg, "head")  # 可重放
    assert set(M3_TABLES) <= _inspect(url)[0]


def test_m3_migrations_match_orm(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """M3 四张表迁移建出的列 == ORM 列 (``alembic check`` 的 sqlite 版)."""
    url = f"sqlite:///{tmp_path / 'm3_match.db'}"
    monkeypatch.setattr(settings, "database_url", url)
    _create_legacy_tables(url)
    cfg = _alembic_config()
    command.stamp(cfg, "a3f7c9d21b45")
    command.upgrade(cfg, "head")
    _, columns, _ = _inspect(url)
    for model in (GenerationJob, AssessmentAttempt, AssessmentAnswer, CourseProgressRow):
        expected = {c.name for c in model.__table__.columns}
        assert expected == columns[model.__tablename__], (
            f"{model.__tablename__} 列漂移: {expected ^ columns[model.__tablename__]}"
        )


def test_single_head_chains_m1_m2_m3() -> None:
    """单 head + 挂链正确: M3(T5) 修 M2(T4), M2 修 M1, M1 修 P1-era head."""
    script = ScriptDirectory.from_config(_alembic_config())
    assert script.get_heads() == [M3_REVISION]
    assert script.get_revision(M3_REVISION).down_revision == M2_REVISION
    assert script.get_revision(M2_REVISION).down_revision == "c9a1f4e7b208"
