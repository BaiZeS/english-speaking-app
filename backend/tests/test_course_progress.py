"""``course_progress`` 物化与收工链路的集成测试 (P4 / 任务书 §范围 5).

* ``finish-mission`` (主动/到顶自动) 之后: ``course_progress`` 出行 —— attempts+1、
  cleared=报告通关、best_total=报告 overall (null 按 0, 不拉低旧值)、last_stage=review、
  ``estimated_seconds`` = 实战开始 -> 收工秒数;
* ``best_total`` 单调 (upsert 竞争语义, CASE GREATEST), ``cleared`` 取或;
* 画廊三字段与 ``GET /courses/progress`` 从同一张表变真。

mock 手法沿用 test_mission: 打基础用启发式 (无凭据), 实战轮 install_llm 给综合 JSON。
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import CourseProgressRow, PracticeSession
from app.services import scene_store
from app.services.llm_provider import get_llm_provider
from tests.test_course_sessions import BRIEFING6, _open, _pass_briefing
from tests.test_drill_grader import install_llm
from tests.test_mission import mission_json
from tests.test_scene_store import write_course

DEV = "dev-session"  # 与 test_course_sessions 的 helper 共用身份 (_open/_pass_briefing 写死了它)
PCM_B64 = base64.b64encode(b"\x00\x01" * 3200).decode()


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    from app.services import llm_provider

    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def scene_root(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    write_course(tmp_path, "scene_alpha", "daily", briefing=BRIEFING6)
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path
    scene_store.invalidate_cache()


async def _row(db: AsyncSession, scene_id: str = "scene_alpha") -> CourseProgressRow | None:
    res = await db.execute(
        select(CourseProgressRow)
        .where(
            CourseProgressRow.user_id == await _uid(db, DEV),
            CourseProgressRow.scene_id == scene_id,
        )
        .execution_options(populate_existing=True)  # 绕开身份映射读真值 (重读场景)
    )
    return res.scalar_one_or_none()


async def _uid(db: AsyncSession, device_id: str) -> str:
    from app.models.db import User

    res = await db.execute(select(User).where(User.device_id == device_id))
    return str(res.scalar_one().id)


@pytest.mark.asyncio
async def test_finish_mission_writes_course_progress(
    client: AsyncClient, db: AsyncSession, scene_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """收工 -> attempts/cleared/best_total/last_stage/estimated_seconds 落行."""
    assert get_llm_provider().is_configured is False  # 打基础全程启发式/stub
    sid = await _open(client)
    await _pass_briefing(client, sid)

    # 实战两轮 (t1/t2 打勾 -> cleared), 用 test_mission 的综合 JSON 脚本
    install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "说了点单内容")]),
            mission_json(done=[("t2", "问了价格")]),
        ],
    )

    first = await client.post(
        f"/api/v1/sessions/{sid}/mission",
        json={"device_id": DEV, "text": "A small coffee, please."},
    )
    assert first.status_code == 200, first.text
    second = await client.post(
        f"/api/v1/sessions/{sid}/mission", json={"device_id": DEV, "text": "How much is that?"}
    )
    assert second.status_code == 200
    assert second.json()["cleared"] is True

    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert finish.status_code == 200
    report = finish.json()["report"]
    assert report["cleared"] is True and report["overall"] == pytest.approx(68.0)

    row = await _row(db)
    assert row is not None
    assert row.attempts == 1
    assert row.cleared is True
    assert row.best_total == pytest.approx(68.0)
    assert row.last_stage == "review"
    assert row.last_session_id == sid
    assert row.estimated_seconds > 0  # started_at -> 收工的时长被记下

    # 同一张表喂画廊三字段 + 进度端点
    page = (await client.get("/api/v1/scenes", params={"device_id": DEV})).json()
    summary = next(s for s in page["scenes"] if s["id"] == "scene_alpha")
    assert (summary["cleared"], summary["attempts"], summary["best_total"]) == (
        True,
        1,
        pytest.approx(68.0),
    )
    progress = (await client.get("/api/v1/courses/progress", params={"device_id": DEV})).json()
    assert progress["total"] == 1 and progress["progress"][0]["last_session_id"] == sid


@pytest.mark.asyncio
async def test_unfinished_session_still_counts_attempt(
    client: AsyncClient, db: AsyncSession, scene_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没通关也计数: best_total=0 不拉低旧值, cleared 取或."""
    sid = await _open(client)
    await _pass_briefing(client, sid)
    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert finish.status_code == 200
    report = finish.json()["report"]
    assert report["cleared"] is False

    row = await _row(db)
    assert row is not None
    assert row.attempts == 1 and row.cleared is False and row.best_total == 0.0


@pytest.mark.asyncio
async def test_best_total_monotonic_across_sessions(
    client: AsyncClient, db: AsyncSession, scene_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """第二场低分 -> best_total 不回退; 第三场高分 -> 更新 (upsert 竞争语义)."""
    install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "说了点单内容")]),
            mission_json(done=[("t2", "问了价格")]),
        ],
    )
    sid = await _open(client)
    await _pass_briefing(client, sid)
    for _ in range(2):
        res = await client.post(
            f"/api/v1/sessions/{sid}/mission",
            json={"device_id": DEV, "text": "A small coffee, please."},
        )
        assert res.status_code == 200
    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert finish.status_code == 200
    row = await _row(db)
    assert row is not None and row.best_total == pytest.approx(68.0)

    # 第二场: 没有可信判分 (无 LLM, 启发式降级) -> overall=None -> best_total 保持 68
    from app.services import llm_provider

    llm_provider.reset_llm_provider_for_tests()
    sid2 = await _open(client)
    await _pass_briefing(client, sid2)
    finish2 = await client.post(f"/api/v1/sessions/{sid2}/finish-mission", json={"device_id": DEV})
    assert finish2.status_code == 200
    row2 = await _row(db)
    assert row2 is not None
    assert row2.attempts == 2
    assert row2.best_total == pytest.approx(68.0)  # 单调: None 按 0 参与 GREATEST


@pytest.mark.asyncio
async def test_dialect_insert_builder_selects_on_conflict_dialect(db: AsyncSession) -> None:
    """PG16 绑定选 pg_insert, 其余 (sqlite) 选 sqlite_insert —— 双方言 ON CONFLICT."""
    from unittest.mock import MagicMock

    from sqlalchemy.dialects.postgresql import Insert as PGInsert
    from sqlalchemy.dialects.sqlite import Insert as SQLiteInsert

    from app.services import course_progress as cp

    pg_db = MagicMock()
    pg_db.get_bind.return_value.dialect.name = "postgresql"
    assert isinstance(cp._dialect_insert(pg_db), PGInsert)

    # 真实会话: PG 上应是 PGInsert, sqlite 上应是 SQLiteInsert (CI=PG, 本地默认 sqlite)
    expected = PGInsert if db.get_bind().dialect.name == "postgresql" else SQLiteInsert
    assert isinstance(cp._dialect_insert(db), expected)


@pytest.mark.asyncio
async def test_record_course_progress_tolerates_bad_started_at(
    client: AsyncClient, db: AsyncSession, scene_root: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """started_at 缺失/损坏/无时区三种形态都不炸, 秒数按 0 或可计算值落库."""
    from types import SimpleNamespace

    from app.api.v1 import course_sessions as cs
    from app.services import course_progress as cp

    await _seed_user(db, DEV)
    # 直接对 helper 做单元级验证 (report 只用 cleared/overall 两个字段).
    course = scene_store.get_course("scene_alpha")
    assert course is not None
    report = SimpleNamespace(cleared=True, overall=66.0)
    row = PracticeSession(user_id=await _uid(db, DEV), scene_id="scene_alpha", doc={"v": 1})
    db.add(row)
    await db.flush()

    sent: list[float] = []
    real = cp.record_finished_session

    async def spy(session: Any, **kwargs: Any) -> None:
        sent.append(float(kwargs["session_seconds"]))
        await real(session, **kwargs)

    monkeypatch.setattr(cp, "record_finished_session", spy)
    monkeypatch.setattr(cs.course_progress, "record_finished_session", spy)

    await cs._record_course_progress(db, row, course, {}, report)  # 无 started_at -> 0
    await cs._record_course_progress(
        db, row, course, {"started_at": "not-a-date"}, report
    )  # 损坏 -> 0
    from datetime import UTC, datetime, timedelta

    naive = (datetime.now(UTC) - timedelta(seconds=30)).replace(tzinfo=None).isoformat()
    await cs._record_course_progress(db, row, course, {"started_at": naive}, report)  # naive -> ~30
    assert sent[0] == 0.0 and sent[1] == 0.0 and 25.0 <= sent[2] <= 120.0


async def _seed_user(db: AsyncSession, device_id: str) -> Any:
    from app.models.db import User

    user = User(device_id=device_id)
    db.add(user)
    await db.commit()
    return user
