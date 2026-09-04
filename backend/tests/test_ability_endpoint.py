"""``GET /api/v1/ability`` 契约测试 (§5.3/§5.6 读侧, 阶段 P3).

钉住 P7 (能力画像页) 要吃的形状: 画像快照 + 4 轴雷达 + 轨迹序列 + 每维 n +
CEFR 字段 (测评前 null)。用 ``ability_engine.record_step_evidence`` 灌真事件
(未门控 + 门控混合), 不走 HTTP 写侧 —— 读侧口径独立于端点闭环验证。
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AbilityEvent, User
from app.services import ability_engine
from app.services.ability_engine import ALPHA, DIMENSIONS
from app.services.drill_grader import AbilityEvidence

DEV = "dev-ability-api"


def ev(
    dimension: str, score: float, *, source: str = "llm", weight: float = 1.0, **kw: object
) -> AbilityEvidence:
    return AbilityEvidence.model_validate(
        {"dimension": dimension, "score": score, "source": source, "weight": weight, **kw}
    )


async def _record(
    db: AsyncSession, user_id: str, evidence: list[AbilityEvidence], step: str = "f1"
) -> None:
    await ability_engine.record_step_evidence(
        db, user_id=user_id, session_id="", step_id=step, evidence=evidence
    )
    await db.commit()


@pytest.mark.asyncio
async def test_ability_requires_identity_and_validates_days(client: AsyncClient) -> None:
    res = await client.get("/api/v1/ability")
    assert res.status_code == 400 and res.json()["error"]["code"] == "IDENTITY_REQUIRED"
    days = await client.get("/api/v1/ability", params={"device_id": DEV, "days": 14})
    assert days.status_code == 400 and days.json()["error"]["code"] == "ABILITY_DAYS_INVALID"
    ok = await client.get("/api/v1/ability", params={"device_id": DEV, "days": 7})
    assert ok.status_code == 200 and ok.json()["days"] == 7


@pytest.mark.asyncio
async def test_unknown_device_gets_empty_profile_view(client: AsyncClient) -> None:
    res = await client.get("/api/v1/ability", params={"device_id": "dev-never-seen"})
    assert res.status_code == 200
    body = res.json()
    assert body["user_found"] is False and body["user_id"] is None
    assert body["profile"] == dict.fromkeys(DIMENSIONS, None)
    assert body["n"] == dict.fromkeys(DIMENSIONS, 0)
    assert [axis["dimension"] for axis in body["radar"]] == list(DIMENSIONS)
    assert all(axis["score"] is None and axis["max"] == 100.0 for axis in body["radar"])
    assert body["cefr_level"] is None and body["assessment_cefr"] is None
    assert body["band_locked"] is False and body["derived_level"] is None
    assert body["trajectory"] == [] and body["real_events"] == 0
    assert body["updated_at"] is None
    # 没被读侧悄悄注册
    sessions = await client.get("/api/v1/sessions", params={"device_id": "dev-never-seen"})
    assert sessions.json() == []


@pytest.mark.asyncio
async def test_profile_radar_counts_and_cefr_shape(client: AsyncClient, db: AsyncSession) -> None:
    user = User(device_id=DEV)
    db.add(user)
    await db.commit()
    await _record(
        db,
        user.id,
        [
            ev("pronunciation", 80.0, source="xunfei", ise_ref_mode="exact_reference"),
            ev("grammar", 70.0),
            ev("vocabulary", 60.0),
        ],
    )
    await _record(
        db,
        user.id,
        [
            ev("pronunciation", 60.0, source="xunfei"),
            ev("fluency", 50.0, source="heuristic", weight=0.0, ise_ref_mode="exact_reference"),
        ],
        step="f2",
    )
    res = await client.get("/api/v1/ability", params={"device_id": DEV, "days": 7})
    assert res.status_code == 200
    body = res.json()
    assert body["user_found"] is True and body["updated_at"].endswith("+00:00")
    # 80 种子 -> 80 + 0.25*(60-80) = 75.0
    assert ALPHA["pronunciation"] == 0.25
    assert body["profile"]["pronunciation"] == pytest.approx(75.0)
    assert body["profile"]["grammar"] == pytest.approx(70.0)
    assert body["profile"]["fluency"] is None  # heuristic w=0: 没种子就不是 0 分
    assert body["n"]["pronunciation"] == 2 and body["n"]["grammar"] == 1
    assert body["n"]["fluency"] == 0
    pron_axis = next(a for a in body["radar"] if a["dimension"] == "pronunciation")
    assert pron_axis["score"] == pytest.approx(75.0) and pron_axis["n"] == 2
    assert body["real_events"] == 4  # 5 条流水 - 1 条被门控

    point = body["trajectory"][0]
    assert point["date"] == datetime.now(UTC).date().isoformat()
    assert point["pronunciation"] == pytest.approx((80.0 + 60.0) / 2)  # 日均值口径
    assert point["grammar"] == pytest.approx(70.0) and point["fluency"] is None
    assert point["events"] == 4
    # 权威 CEFR: 测评 (P4) 前恒 null; 四维映射只作为辅助字段出现
    assert body["cefr_level"] is None
    assert body["derived_level"] == "B1"  # (75+70+60)/3 = 68.3 -> B1 档


@pytest.mark.asyncio
async def test_stub_events_never_move_the_profile_through_the_endpoint(
    client: AsyncClient, db: AsyncSession
) -> None:
    """本机等价路径: 全是 stub/heuristic 证据时, GET /ability 永远空画像."""
    user = User(device_id="dev-all-stub")
    db.add(user)
    await db.commit()
    await _record(
        db,
        user.id,
        [
            ev("pronunciation", 95.0, source="stub", weight=0.0, ise_ref_mode="exact_reference"),
            ev("grammar", 70.0, source="heuristic", weight=0.0),
        ],
    )
    body = (await client.get("/api/v1/ability", params={"user_id": user.id})).json()
    assert body["profile"] == dict.fromkeys(DIMENSIONS, None)
    assert body["n"] == dict.fromkeys(DIMENSIONS, 0)
    assert body["real_events"] == 0 and body["trajectory"] == []
    assert body["derived_level"] is None


@pytest.mark.asyncio
async def test_trajectory_respects_the_days_window(client: AsyncClient, db: AsyncSession) -> None:
    user = User(device_id="dev-window")
    db.add(user)
    await db.commit()
    await _record(db, user.id, [ev("grammar", 50.0)])
    # 把这条流水推到 60 天前: 7/30 窗口不显示, 90 窗口显示 (画像值不随窗口变).
    old = datetime.now(UTC) - timedelta(days=60)
    await db.execute(update(AbilityEvent).values(created_at=old))
    await db.commit()
    for days, expect_points in ((7, 0), (30, 0), (90, 1)):
        body = (
            await client.get("/api/v1/ability", params={"device_id": "dev-window", "days": days})
        ).json()
        assert body["days"] == days
        assert len(body["trajectory"]) == expect_points
        assert body["n"]["grammar"] == 1
    body = (
        await client.get("/api/v1/ability", params={"device_id": "dev-window", "days": 90})
    ).json()
    assert body["trajectory"][0]["grammar"] == pytest.approx(50.0)
