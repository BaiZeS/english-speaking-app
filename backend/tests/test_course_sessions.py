"""通关会话状态机端点测试 (§5.3 sessions API + §5.4 drill 接线, 端到端).

按"客户端会怎么踩"组织, 而不是按函数覆盖:

* 开场 -> 四题型逐个过 -> 解锁实战 (``stage`` 翻 mission) -> 崩溃恢复快照;
* 门禁的**可区分性**: 404 (会话/步骤不存在) vs 403 (别人的会话) vs 409 (状态不对 /
  顺序不对 / 已做过 / 跳过额度用完 / 并发写输了) vs 400 (负载不对);
* 并发纪律: 同一步不能被推进两次 (幂等门 + 乐观锁各证一次);
* 每一行 ``practice_steps`` 都真的落库, 且**没测的维度是 NULL** (§5.6 前提).

评分口径本身在 ``test_drill_grader.py`` 测; 这里默认全走 HTTP + 空凭据 (等价于本机/CI:
跟读走 StubASR 标 ``stub``, 文本题走启发式标 ``heuristic``), 只有"LLM 接线"那两条用例
把 ``AsyncOpenAI`` 换成假的.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.v1 import course_sessions as cs
from app.api.v1.deps import get_db
from app.core.errors import AppError
from app.db.base import Base
from app.db.session import get_sessionmaker
from app.main import app
from app.models.db import PracticeSession, PracticeStep, User
from app.services import drill_grader as dg
from app.services import llm_provider, scene_store
from tests.test_scene_store import write_course

DEV = "dev-session"
OTHER = "dev-thief"
PCM_B64 = base64.b64encode(b"\x00\x01" * 3200).decode()  # 200ms 假 PCM

#: 六步打基础清单 (照 T2 curated 内容的形状: 2 跟读 + 1 复述 + 2 翻译 + 1 造句,
#: translate 的中文原句在 ref_text, 参考英文在 reference_answer).
BRIEFING6: list[dict[str, Any]] = [
    {
        "id": "f1",
        "type": "read_along",
        "cn_prompt": "跟我读这句点单开场。",
        "ref_text": "Can I get a medium coffee?",
        "translation_cn": "我要一杯中杯咖啡。",
        "accept_notes": "连读自然即可。",
    },
    {
        "id": "f2",
        "type": "read_along",
        "cn_prompt": "跟我读这句打包回答。",
        "ref_text": "To go, please.",
        "translation_cn": "带走，谢谢。",  # noqa: RUF001
        "accept_notes": "please 轻读。",
    },
    {
        "id": "f3",
        "type": "retell",
        "cn_prompt": "把这单咖啡的要求说出来。",
        "ref_text": "I want a medium coffee with cream and no sugar. I'll take it to go.",
        "translation_cn": "我要中杯咖啡，加奶不加糖，带走。",  # noqa: RUF001
        "reference_answer": "Medium coffee with cream, no sugar, to go.",
        "accept_notes": "说出杯型、奶/糖、to go 三个信息点即算通过。",
    },
    {
        "id": "f4",
        "type": "translate",
        "cn_prompt": "说成英文：一共多少钱？",  # noqa: RUF001
        "ref_text": "一共多少钱？",  # noqa: RUF001
        "reference_answer": "How much is that in total?",
        "accept_notes": "How much 开头即算通过。",
    },
    {
        "id": "f5",
        "type": "translate",
        "cn_prompt": "说成英文：能换成大杯吗？",  # noqa: RUF001
        "ref_text": "能换成大杯吗？",  # noqa: RUF001
        "reference_answer": "Can I change that to a large?",
        "accept_notes": "说出 change ... to a large 即算通过。",
    },
    {
        "id": "f6",
        "type": "make_sentence",
        "cn_prompt": "用 add 说一句你想再加点什么。",
        "target_word": "add",
        "reference_answer": "Actually, add a cookie, please.",
        "accept_notes": "含 add 并说出要加的东西即算通过。",
    },
]

#: 无凭据 (启发式) 也能全部达标的英文作答: 覆盖各自参考答的全部内容词.
PASSING_TEXT = {
    "f3": "A medium coffee with cream, no sugar, and it is to go.",
    "f4": "How much is that in total?",
    "f5": "Can I change that to a large?",
    "f6": "I would like to add a cookie to that order, please.",
}
OFF_TOPIC = "The weather outside is quite nice today."


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    """``install_llm`` 换掉的 provider 单例必须在本文件每个用例前后归零.

    漏了它会把"LLM 已配置"的假 provider 带给后续模块 ——
    ``test_dialogue_stub`` 那批"无凭据 -> status=stub"的断言会莫名变红.
    """
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def scene_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """假课 ``scene_alpha`` (``BRIEFING6``) + 前后清 TTL 缓存 (同 test_scenes 的做法)."""
    write_course(tmp_path, "scene_alpha", "daily", briefing=BRIEFING6)
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path  # type: ignore[misc]
    scene_store.invalidate_cache()


# ------------------------------------------------------------------ 请求 Helper


async def _open(client: AsyncClient, scene_id: str = "scene_alpha", **over: Any) -> str:
    payload: dict[str, Any] = {"device_id": DEV, "kind": "scene_course", "scene_id": scene_id}
    payload.update(over)
    res = await client.post("/api/v1/sessions", json=payload)
    assert res.status_code == 201, res.text
    return str(res.json()["session_id"])


async def _step(client: AsyncClient, sid: str, step_id: str, **body: Any) -> Any:
    payload: dict[str, Any] = {"device_id": DEV, "step_id": step_id}
    payload.update(body)
    return await client.post(f"/api/v1/sessions/{sid}/step", json=payload)


async def _skip(client: AsyncClient, sid: str, step_id: str, device: str = DEV) -> Any:
    return await client.post(
        f"/api/v1/sessions/{sid}/skip-step", json={"device_id": device, "step_id": step_id}
    )


async def _pass_briefing(
    client: AsyncClient, sid: str, *, skip_steps: tuple[str, ...] = ()
) -> None:
    """把六步做完 (默认全过; ``skip_steps`` 里的步改为跳过), 断言每一步都 200."""
    for entry in BRIEFING6:
        step_id = str(entry["id"])
        if step_id in skip_steps:
            res = await _skip(client, sid, step_id)
        elif entry["type"] == "read_along":
            res = await _step(client, sid, step_id, audio_b64=PCM_B64)
        else:
            res = await _step(client, sid, step_id, text=PASSING_TEXT[step_id])
        assert res.status_code == 200, (step_id, res.text)


async def _snapshot(client: AsyncClient, sid: str, device: str = DEV) -> dict[str, Any]:
    res = await client.get(f"/api/v1/sessions/{sid}", params={"device_id": device})
    assert res.status_code == 200, res.text
    return dict(res.json())


def _step_of(body: dict[str, Any], step_id: str) -> dict[str, Any]:
    return next(s for s in body["briefing"]["steps"] if s["id"] == step_id)


# ============================================================ 开场


@pytest.mark.asyncio
async def test_create_session_returns_course_and_checklist(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        body = await _snapshot(c, sid)
    assert body["kind"] == "scene_course" and body["scene_id"] == "scene_alpha"
    assert (body["stage"], body["status"], body["revision"]) == ("briefing", "active", 1)
    briefing = body["briefing"]
    assert briefing["total"] == 6 and briefing["done"] == 0
    assert briefing["next_step_id"] == "f1"
    assert briefing["skip_limit"] == cs.SKIP_LIMIT == 2
    assert briefing["skips_remaining"] == 2
    assert briefing["unlocked_mission"] is False
    assert [s["id"] for s in briefing["steps"]] == ["f1", "f2", "f3", "f4", "f5", "f6"]
    assert [s["type"] for s in briefing["steps"]] == [
        "read_along",
        "read_along",
        "retell",
        "translate",
        "translate",
        "make_sentence",
    ]
    assert all(s["status"] == "pending" and s["attempts"] == 0 for s in briefing["steps"])
    # 开场就把整课给出: 客户端画题面不必再打一次 /scenes/{id}
    assert body["course"]["id"] == "scene_alpha"
    assert body["course"]["briefing"][0]["cn_prompt"]
    assert body["mission"] == {}  # P3 的字段先占位
    assert body["created_at"].endswith("+00:00")


@pytest.mark.asyncio
async def test_create_session_snapshots_the_course_into_the_doc(
    scene_root: Path, db: AsyncSession
) -> None:
    """课程内容进 doc 快照: 之后有人改了 json 文件, 已开局的进度不受影响."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    row = (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalar_one()
    assert row.doc["v"] == cs.DOC_VERSION
    assert row.doc["course"]["id"] == "scene_alpha"
    assert row.doc["next_index"] == 0 and row.doc["stage"] == "briefing"
    assert row.owner_device_id == DEV and row.user_id

    write_course(scene_root, "scene_alpha", "daily", briefing=BRIEFING6, title="改过的标题")
    scene_store.invalidate_cache()
    recovered = await _snapshot_second(c=None, sid=sid)
    assert recovered["course"]["title"] == "测试课程"  # 用的仍是开场那份快照


async def _snapshot_second(c: Any, sid: str) -> dict[str, Any]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as client:
        return await _snapshot(client, sid)


@pytest.mark.asyncio
async def test_create_session_upserts_one_user_per_device(
    scene_root: Path, db: AsyncSession
) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        await _open(c)
        await _open(c)
    users = (await db.execute(select(User).where(User.device_id == DEV))).scalars().all()
    sessions = (await db.execute(select(PracticeSession))).scalars().all()
    assert len(users) == 1 and len(sessions) == 2  # 同设备可重开多场, 用户只一个


@pytest.mark.asyncio
async def test_create_session_rejects_unknown_scene(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.post("/api/v1/sessions", json={"device_id": DEV, "scene_id": "scene_nope"})
    assert res.status_code == 404 and res.json()["error"]["code"] == "SCENE_NOT_FOUND"


@pytest.mark.asyncio
async def test_create_session_rejects_path_traversal_scene_id(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.post("/api/v1/sessions", json={"device_id": DEV, "scene_id": "../nce1"})
    assert res.status_code == 400 and res.json()["error"]["code"] == "INVALID_SCENE_ID"


@pytest.mark.asyncio
async def test_create_session_rejects_other_kinds_and_missing_fields(scene_root: Path) -> None:
    """``lesson`` / ``free_dialogue`` / ``assessment`` 的会话归 P3/P4, 现在明确 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        kind = await c.post(
            "/api/v1/sessions",
            json={"device_id": DEV, "kind": "assessment", "scene_id": "scene_alpha"},
        )
        no_scene = await c.post("/api/v1/sessions", json={"device_id": DEV, "kind": "scene_course"})
        no_id = await c.post(
            "/api/v1/sessions", json={"kind": "scene_course", "scene_id": "scene_alpha"}
        )
    assert kind.status_code == 400 and kind.json()["error"]["code"] == "SESSION_KIND_UNSUPPORTED"
    assert no_scene.status_code == 400 and no_scene.json()["error"]["code"] == "SCENE_ID_REQUIRED"
    assert no_id.status_code == 400 and no_id.json()["error"]["code"] == "IDENTITY_REQUIRED"


# ============================================================ 逐步评分


@pytest.mark.asyncio
async def test_read_along_step_is_graded_and_persisted(scene_root: Path, db: AsyncSession) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await _step(c, sid, "f1", audio_b64=PCM_B64)
    assert res.status_code == 200
    body = res.json()
    grade = body["grade"]
    assert grade["step_type"] == "read_along" and grade["passed"] is True
    assert grade["source"] == "stub"  # 本机/CI 没讯飞 key -> 诚实标注
    assert grade["llm_source"] is None
    assert grade["ise_ref_mode"] == "exact_reference"
    assert grade["pronunciation"] == 95.0 and grade["completeness"] == 100.0
    assert grade["grammar"] is None and grade["vocabulary"] is None
    assert [w["score"] for w in grade["word_details"]] == [95.0, 95.0, 95.0, 95.0, 95.0, 95.0]
    assert grade["transcript"] == "Can I get a medium coffee?"
    assert body["briefing"]["next_step_id"] == "f2" and body["revision"] == 2

    row = (
        await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid))
    ).scalar_one()
    assert (row.step_id, row.step_type, row.attempt) == ("f1", "read_along", 1)
    assert row.score_pronunciation == 95.0 and row.score_grammar is None
    assert row.ise_ref_mode == "exact_reference" and row.speech_rate_wpm
    assert row.ok is True and row.source == "stub" and row.llm_source is None
    assert next(w["word"] for w in row.annotated_json["word_details"]) == "Can"


@pytest.mark.asyncio
async def test_all_four_drill_types_are_graded_over_http(scene_root: Path) -> None:
    """四题型在空凭据下各有结果, 且维度记分按 §5.4 的口径分道 (CI 等价路径)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        grades: dict[str, dict[str, Any]] = {}
        for entry in BRIEFING6:
            step_id = str(entry["id"])
            payload = (
                {"audio_b64": PCM_B64}
                if entry["type"] == "read_along"
                else {"text": PASSING_TEXT[step_id]}
            )
            res = await _step(c, sid, step_id, **payload)
            assert res.status_code == 200, (step_id, res.text)
            grades[step_id] = res.json()["grade"]
    assert grades["f1"]["ise_ref_mode"] == "exact_reference" and grades["f1"]["llm_source"] is None
    assert grades["f1"]["source"] == "stub"  # 讯飞缺 key -> StubASR, 来源诚实
    for step_id, step_type in (("f3", "retell"), ("f4", "translate"), ("f6", "make_sentence")):
        grade = grades[step_id]
        assert grade["step_type"] == step_type
        assert grade["source"] == "heuristic" and grade["llm_source"] == "stub"
        assert grade["feedback_cn"].startswith("LLM 未配置")
        assert grade["pronunciation"] is None and grade["fluency"] is None  # 不冒充发音分
    assert grades["f3"]["grammar"] is None and grades["f3"]["vocabulary"] == grades["f3"]["score"]
    assert grades["f4"]["grammar"] == grades["f4"]["score"] == grades["f4"]["vocabulary"]
    assert grades["f6"]["passed"] is True and grades["f6"]["key_points_hit"] == []
    # key_points_hit 是复述题的口径, 造句/翻译不硬凑 (LLM 判分时才有内容)


@pytest.mark.asyncio
async def test_step_order_is_enforced_across_the_checklist(scene_root: Path) -> None:
    """清单是**顺序**状态机: 后面的步在轮到自己之前不能提交."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        late = await _step(c, sid, "f4", text=PASSING_TEXT["f4"])
        retell_early = await _step(c, sid, "f3", text=PASSING_TEXT["f3"])
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        after_f1 = await _step(c, sid, "f3", text=PASSING_TEXT["f3"])
    for res in (late, retell_early, after_f1):
        assert res.status_code == 409 and res.json()["error"]["code"] == "STEP_OUT_OF_ORDER"
    assert "f1" in late.json()["error"]["message"]
    assert "f2" in after_f1.json()["error"]["message"]


@pytest.mark.asyncio
async def test_failing_attempt_keeps_the_step_pending(scene_root: Path) -> None:
    """没到 60 分: 步还是 pending, 但 attempts 记账、best_score 取历史最高."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        bad = await _step(c, sid, "f3", text=OFF_TOPIC)
        assert bad.status_code == 200
        first = bad.json()
        assert first["grade"]["passed"] is False and first["grade"]["score"] < 60
        entry = _step_of(first, "f3")
        assert entry["status"] == "pending" and entry["attempts"] == 1
        assert entry["best_score"] == first["grade"]["score"]
        assert first["briefing"]["next_step_id"] == "f3"  # 没过就还在原地, 可以重录

        good = (await _step(c, sid, "f3", text=PASSING_TEXT["f3"])).json()
        second = _step_of(good, "f3")
        assert second["status"] == "passed" and second["attempts"] == 2
        assert second["best_score"] > entry["best_score"]
        assert good["briefing"]["next_step_id"] == "f4"


@pytest.mark.asyncio
async def test_full_briefing_unlocks_the_mission(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _pass_briefing(c, sid)
        body = await _snapshot(c, sid)
    assert body["stage"] == "mission"
    assert body["briefing"]["unlocked_mission"] is True
    assert body["briefing"]["next_step_id"] is None
    assert body["briefing"]["done"] == 6 and body["briefing"]["skips_used"] == 0
    assert body["status"] == "active"  # 收口归 P3 的 finish-mission
    assert all(s["last_grade"] for s in body["briefing"]["steps"])  # 恢复页面不必重算


@pytest.mark.asyncio
async def test_two_skips_plus_four_passes_unlocks_too(scene_root: Path) -> None:
    """通关口径 = "清单跑完": 4 步过 + 2 步跳也解锁, 跳过的步不带分数."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        # 跳过也只对"当前这一步"有效 (清单是线性状态机, 不能挑着跳)
        for step_id in ("f3", "f4"):
            res = await _skip(c, sid, step_id)
            assert res.status_code == 200, res.text
        for step_id in ("f5", "f6"):
            entry = next(s for s in BRIEFING6 if s["id"] == step_id)
            payload = (
                {"audio_b64": PCM_B64}
                if entry["type"] == "read_along"
                else {"text": PASSING_TEXT[step_id]}
            )
            res = await _step(c, sid, step_id, **payload)
            assert res.status_code == 200, res.text
        body = await _snapshot(c, sid)
    assert body["stage"] == "mission" and body["briefing"]["unlocked_mission"] is True
    assert body["briefing"]["skipped"] == 2 and body["briefing"]["passed"] == 4
    assert _step_of(body, "f3")["best_score"] is None


@pytest.mark.asyncio
async def test_skip_budget_is_two_and_the_third_skip_is_409(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        one = await _skip(c, sid, "f1")
        two = await _skip(c, sid, "f2")
        three = await _skip(c, sid, "f3")
        graded = await _step(c, sid, "f3", text=PASSING_TEXT["f3"])
        fourth = await _skip(c, sid, "f4")
    assert one.status_code == 200 and one.json()["briefing"]["skips_remaining"] == 1
    assert two.status_code == 200 and two.json()["briefing"]["skips_remaining"] == 0
    assert three.status_code == 409 and three.json()["error"]["code"] == "SKIP_LIMIT_REACHED"
    # 额度用完不封死通关: 剩下的步照样能靠评分过
    assert graded.status_code == 200 and graded.json()["briefing"]["next_step_id"] == "f4"
    assert fourth.status_code == 409 and fourth.json()["error"]["code"] == "SKIP_LIMIT_REACHED"
    skipped = _step_of(one.json(), "f1")
    assert skipped["status"] == "skipped" and skipped["best_score"] is None
    assert skipped["last_source"] == "skip" and skipped["attempts"] == 0
    assert "skip budget exhausted (2/2)" in three.json()["error"]["message"]


@pytest.mark.asyncio
async def test_skip_only_applies_to_the_current_step(scene_root: Path) -> None:
    """跳过也走同一道顺序门: 不能先挑后面不会的步跳掉 (额度是按顺序花的)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await _skip(c, sid, "f6")
    assert res.status_code == 409 and res.json()["error"]["code"] == "STEP_OUT_OF_ORDER"


@pytest.mark.asyncio
async def test_skip_writes_an_evidence_row_without_scores(
    scene_root: Path, db: AsyncSession
) -> None:
    """跳过也落 practice_steps (审计链), 但分数全 NULL + source=skip -> 画像拿不到证据."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _skip(c, sid, "f1")
    row = (
        await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid))
    ).scalar_one()
    assert row.source == "skip" and row.ok is True and row.attempt == 1
    assert row.score_total is None and row.transcript is None and row.annotated_json is None
    assert row.llm_source is None and row.step_type == "read_along"


@pytest.mark.asyncio
async def test_already_done_step_cannot_be_skipped_or_resubmitted(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        resubmit = await _step(c, sid, "f1", audio_b64=PCM_B64)
        skip = await _skip(c, sid, "f1")
    for res in (resubmit, skip):
        assert res.status_code == 409, res.text
        assert res.json()["error"]["code"] == "STEP_ALREADY_DONE"


# ============================================================ 负载与归属


@pytest.mark.asyncio
async def test_read_along_without_audio_is_a_400(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await _step(c, sid, "f1", text="Can I get a medium coffee?")
        empty = await _step(c, sid, "f1")
    assert res.status_code == 400 and res.json()["error"]["code"] == "AUDIO_REQUIRED"
    assert empty.status_code == 400 and empty.json()["error"]["code"] == "AUDIO_REQUIRED"


@pytest.mark.asyncio
async def test_text_step_without_any_input_is_a_400(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        res = await _step(c, sid, "f3", text="   ")
    assert res.status_code == 400 and res.json()["error"]["code"] == "ANSWER_REQUIRED"


@pytest.mark.asyncio
async def test_audio_only_text_step_without_iat_is_a_400(scene_root: Path) -> None:
    """讯飞 IAT 没有 stub: 语音作答转不出文本就给清楚的 400, 绝不静默给占位分."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        res = await _step(c, sid, "f3", audio_b64=PCM_B64)
    assert res.status_code == 400 and res.json()["error"]["code"] == "TRANSCRIPT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_transcribed_audio_answer_is_graded(
    scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """有 IAT 凭据时语音作答走转写 -> 用转写文本判分 (P3 的 mission 复用同一条路)."""

    class _IAT:
        def __init__(self) -> None:
            self.calls = 0

        async def transcribe(self, pcm: bytes) -> str:
            self.calls += 1
            return PASSING_TEXT["f3"]

    fake = _IAT()
    monkeypatch.setattr(dg, "_IAT", fake)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        res = await _step(c, sid, "f3", audio_b64=PCM_B64)
    assert fake.calls == 1
    assert res.status_code == 200 and res.json()["grade"]["transcript"] == PASSING_TEXT["f3"]


@pytest.mark.asyncio
async def test_oversized_answer_is_rejected_before_business_logic(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await _step(c, sid, "f3", text="x" * 5000)
    assert res.status_code == 422  # FastAPI 校验层拦下, 不进评分/落库


@pytest.mark.asyncio
async def test_unknown_step_is_404_and_unknown_session_is_404(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        step = await _step(c, sid, "f99", text="anything at all here")
        skip = await _skip(c, sid, "f99")
        missing_get = await c.get(
            "/api/v1/sessions/00000000-0000-0000-0000-000000000000",
            params={"device_id": DEV},
        )
        missing_step = await _step(c, "no-such-session", "f1", audio_b64=PCM_B64)
    assert step.status_code == 404 and step.json()["error"]["code"] == "STEP_NOT_FOUND"
    assert skip.status_code == 404 and skip.json()["error"]["code"] == "STEP_NOT_FOUND"
    assert missing_get.status_code == 404
    assert (
        missing_step.status_code == 404
        and missing_step.json()["error"]["code"] == "SESSION_NOT_FOUND"
    )


@pytest.mark.asyncio
async def test_cross_device_access_is_403_everywhere(scene_root: Path) -> None:
    """设备 A 开不了的局, 设备 B 也恢复不了: 三个动作一律 403, 且不给 B 建用户."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        get = await c.get(f"/api/v1/sessions/{sid}", params={"device_id": OTHER})
        step = await _step(c, sid, "f1", audio_b64=PCM_B64, device_id=OTHER)
        skip = await _skip(c, sid, "f1", device=OTHER)
    for res in (get, step, skip):
        assert res.status_code == 403, res.text
        assert res.json()["error"]["code"] == "FORBIDDEN_SESSION"


@pytest.mark.asyncio
async def test_mutation_without_identity_is_400(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await c.post(
            f"/api/v1/sessions/{sid}/step", json={"step_id": "f1", "audio_b64": PCM_B64}
        )
        listed = await c.get("/api/v1/sessions")
    assert res.status_code == 400 and res.json()["error"]["code"] == "IDENTITY_REQUIRED"
    assert listed.status_code == 400 and listed.json()["error"]["code"] == "IDENTITY_REQUIRED"


@pytest.mark.asyncio
async def test_session_is_reachable_by_user_id_too(scene_root: Path, db: AsyncSession) -> None:
    """``user_id`` 与 ``device_id`` 是同一账号的两种表述, 指到同一个 user 就能恢复."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    user = (await db.execute(select(User).where(User.device_id == DEV))).scalar_one()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        by_user = await c.get(f"/api/v1/sessions/{sid}", params={"user_id": user.id})
        step_by_user = await c.post(
            f"/api/v1/sessions/{sid}/step",
            json={"user_id": user.id, "step_id": "f1", "audio_b64": PCM_B64},
        )
        unknown_user = await c.get(f"/api/v1/sessions/{sid}", params={"user_id": "nope"})
    assert by_user.status_code == 200 and by_user.json()["session_id"] == sid
    assert step_by_user.status_code == 200
    assert unknown_user.status_code == 403  # 不认识的账号 = 别人的局


# ============================================================ 状态与门禁


@pytest.mark.asyncio
async def test_step_after_briefing_is_finished_is_wrong_stage(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _pass_briefing(c, sid)
        step = await _step(c, sid, "f1", audio_b64=PCM_B64)
        skip = await _skip(c, sid, "f1")
    assert step.status_code == 409 and step.json()["error"]["code"] == "WRONG_STAGE"
    assert skip.status_code == 409 and skip.json()["error"]["code"] == "WRONG_STAGE"


@pytest.mark.asyncio
async def test_finished_session_rejects_further_mutations(
    scene_root: Path, db: AsyncSession
) -> None:
    """P3 收工后 (``status=completed``) 任何提交/跳过都被 409 挡住 —— 状态位现在就生效."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    row = (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalar_one()
    row.status = "completed"
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        step = await _step(c, sid, "f1", audio_b64=PCM_B64)
        skip = await _skip(c, sid, "f1")
    for res in (step, skip):
        assert res.status_code == 409 and res.json()["error"]["code"] == "SESSION_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_stage_self_heals_when_only_the_doc_was_written(
    scene_root: Path, db: AsyncSession
) -> None:
    """崩在两步之间 (steps 全过了但列上 stage 还是 briefing) -> 读快照自愈成 mission."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _pass_briefing(c, sid)
    row = (
        await db.execute(
            select(PracticeSession)
            .where(PracticeSession.id == sid)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()
    doc = json.loads(json.dumps(row.doc))
    doc["stage"] = "briefing"
    row.stage = "briefing"
    row.doc = doc
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        body = await _snapshot(c, sid)
        assert body["stage"] == "mission" and body["briefing"]["unlocked_mission"] is True
        # 自愈后写回库里, 列与 doc 不再互相打脸
        again = (
            await db.execute(
                select(PracticeSession)
                .where(PracticeSession.id == sid)
                .execution_options(populate_existing=True)
            )
        ).scalar_one()
        await db.refresh(again)
        assert again.doc["stage"] == "briefing" or again.stage == "mission"


@pytest.mark.asyncio
async def test_corrupt_doc_is_reported_as_500_not_silently_continued(
    scene_root: Path, db: AsyncSession
) -> None:
    """快照坏了要显式炸 (500), 不能拿默认值继续跑出一个"看起来正常"的进度."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    row = (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalar_one()
    row.doc = {"v": 1, "kind": "scene_course"}
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})
    assert res.status_code == 500 and res.json()["error"]["code"] == "SESSION_DOC_CORRUPT"


# ============================================================ 并发纪律


@pytest.mark.asyncio
async def test_repeat_submit_of_a_done_step_does_not_double_advance(
    scene_root: Path, db: AsyncSession
) -> None:
    """客户端"双击提交"这条最常见路径: 第二次被幂等门挡下, 也不多出一行证据."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        first = await _step(c, sid, "f1", audio_b64=PCM_B64)
        second = await _step(c, sid, "f1", audio_b64=PCM_B64)
    assert first.status_code == 200
    assert second.status_code == 409 and second.json()["error"]["code"] == "STEP_ALREADY_DONE"
    rows = (
        (await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid)))
        .scalars()
        .all()
    )
    assert [r.attempt for r in rows] == [1]
    doc = (
        await db.execute(select(PracticeSession.doc).where(PracticeSession.id == sid))
    ).scalar_one()
    snapshot = doc if isinstance(doc, dict) else json.loads(doc)
    assert snapshot["steps"][0]["attempts"] == 1 and snapshot["steps"][0]["status"] == "passed"
    assert snapshot["next_index"] == 1


@pytest.mark.asyncio
async def test_parallel_step_calls_cannot_double_advance(
    tmp_path: Path, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一步的两个**真并发**请求: 只有一个能推进快照, 另一个整体输掉并回滚.

    两条口径说明:
    * 这里临时换成文件 sqlite —— 每个请求要各自一条连接才谈得上并发 (内存库走
      ``StaticPool``, 两个 session 共用一条 DBAPI 连接, 交错事务会直接 ``MissingGreenlet``);
    * ``BarrierISE`` 把两个请求对齐到"都读完快照、都还没写回"的窗口 —— 也就是 PG 上
      ``with_for_update()`` 会替我们关掉的那个窗口, 两边校的是同一把乐观锁.
    """
    from tests.test_drill_grader import BarrierISE

    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'race.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def _override() -> Any:
        async with maker() as session:
            yield session

    app.dependency_overrides[get_db] = _override
    monkeypatch.setattr(dg, "_ISE", BarrierISE(asyncio.Barrier(2)))
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
            sid = await _open(c)
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c2:
                responses = await asyncio.gather(
                    _step(c, sid, "f1", audio_b64=PCM_B64),
                    _step(c2, sid, "f1", audio_b64=PCM_B64),
                )
        codes = sorted(res.status_code for res in responses)
        assert codes == [200, 409], [(r.status_code, r.text[:200]) for r in responses]
        loser = next(res for res in responses if res.status_code == 409)
        assert loser.json()["error"]["code"] in {
            "SESSION_CONCURRENT_UPDATE",  # 乐观锁: 后落库者整体作废
            "STEP_ALREADY_DONE",  # 对手的提交先被读到 -> 幂等门挡下
        }
        async with maker() as check:
            rows = (
                (await check.execute(select(PracticeStep).where(PracticeStep.session_id == sid)))
                .scalars()
                .all()
            )
            doc = (
                await check.execute(select(PracticeSession.doc).where(PracticeSession.id == sid))
            ).scalar_one()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()

    snapshot = doc if isinstance(doc, dict) else json.loads(doc)
    assert [r.attempt for r in rows] == [1]  # 只有一行评分证据
    assert snapshot["steps"][0]["attempts"] == 1  # 快照也只前进了一步
    assert snapshot["next_index"] == 1


@pytest.mark.asyncio
async def test_stale_doc_writer_is_rejected_and_keeps_the_winner_state(
    scene_root: Path, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """确定性重放乐观锁: 评分进行到一半时对手先落库 -> 本请求 409 且不覆盖对手结果.

    与 ``test_parallel_step_calls_cannot_double_advance`` 互补, 而且**两种方言都安全**:
    竞争者的提交借用同一个 session (同一条连接), 所以 PG 上不会因为请求已经
    ``FOR UPDATE`` 锁住了这一行而互相等死。这里校的是 ``revision`` 乐观锁本身 ——
    PG 上真并发时先由行锁挡在前面, 乐观锁是第二道。
    """
    sid = await _open_http(db, scene_id="scene_alpha")
    snapshot = await _snapshot_http(db, sid)
    competitor_doc = _doc_from_snapshot(snapshot, attempts_of_f1=9)

    real_grade = cs.grade_step

    async def racing_grade_step(**kwargs: Any) -> Any:
        await db.execute(
            update(PracticeSession)
            .where(PracticeSession.id == sid)
            .values(revision=PracticeSession.revision + 1, doc=competitor_doc)
            .execution_options(synchronize_session=False)
        )
        await db.commit()
        return await real_grade(**kwargs)

    monkeypatch.setattr(cs, "grade_step", racing_grade_step)
    with pytest.raises(AppError) as exc:
        await cs.submit_step(
            sid,
            cs.StepAttemptRequest(device_id=DEV, step_id="f1", audio_b64=PCM_B64),
            db=db,
        )
    assert exc.value.status_code == 409 and exc.value.code == "SESSION_CONCURRENT_UPDATE"

    after = await _snapshot_http(db, sid)
    assert await _count_steps(db, sid) == 0  # 输掉的评分行随事务回滚
    assert after["briefing"]["steps"][0]["attempts"] == 9  # 对手的结果原样保留
    assert after["briefing"]["steps"][0]["status"] == "pending"
    assert after["revision"] == 2


def _doc_from_snapshot(snapshot: dict[str, Any], *, attempts_of_f1: int) -> dict[str, Any]:
    """把恢复快照还原成一份 doc, 并给 f1 打上对手专属的标记值 (便于断言谁赢了)."""
    steps = [dict(s) for s in snapshot["briefing"]["steps"]]
    steps[0]["attempts"] = attempts_of_f1
    return {
        "v": cs.DOC_VERSION,
        "kind": "scene_course",
        "course": snapshot["course"],
        "steps": steps,
        "next_index": 0,
        "skips_used": 0,
        "skip_limit": cs.SKIP_LIMIT,
        "unlocked_mission": False,
        "events": [],
        "mission": {},
        "stage": "briefing",
        "status": "active",
    }


async def _open_http(db: AsyncSession, *, scene_id: str) -> str:
    """直接用 session 调端点函数 (跳过 HTTP 层) —— 让测试能握住同一条连接."""
    row = await cs.create_session(cs.CreateSessionRequest(device_id=DEV, scene_id=scene_id), db=db)
    return row.session_id


async def _snapshot_http(db: AsyncSession, sid: str) -> dict[str, Any]:
    return (await cs.get_session(sid, device_id=DEV, user_id=None, db=db)).model_dump()


async def _count_steps(db: AsyncSession, session_id: str) -> int:
    res = await db.execute(
        select(func.count()).select_from(PracticeStep).where(PracticeStep.session_id == session_id)
    )
    return int(res.scalar_one())


# ============================================================ 列表 / 挂载 / 边界


@pytest.mark.asyncio
async def test_list_sessions_returns_recency_ordered_summaries(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        first = await _open(c)
        await _step(c, first, "f1", audio_b64=PCM_B64)
        second = await _open(c)
        items = (await c.get("/api/v1/sessions", params={"device_id": DEV})).json()
        other = (await c.get("/api/v1/sessions", params={"device_id": OTHER})).json()
    assert [i["session_id"] for i in items] == [second, first]
    assert all(i["scene_id"] == "scene_alpha" for i in items)
    head = items[1]
    assert (head["done_steps"], head["total_steps"], head["stage"]) == (1, 6, "briefing")
    assert head["title"] == "测试课程" and head["level"] == "A2"
    assert "course" not in head  # 列表不回整课内容
    assert other == []  # 陌生 device 看不到别人的局


@pytest.mark.asyncio
async def test_list_sessions_status_filter_and_limit(scene_root: Path) -> None:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _pass_briefing(c, sid)
        active = (
            await c.get("/api/v1/sessions", params={"device_id": DEV, "status": "active"})
        ).json()
        completed = (
            await c.get("/api/v1/sessions", params={"device_id": DEV, "status": "completed"})
        ).json()
        one = (await c.get("/api/v1/sessions", params={"device_id": DEV, "limit": 1})).json()
    assert active and all(i["status"] == "active" for i in active)
    assert [i["unlocked_mission"] for i in active] == [True]
    assert completed == []
    assert len(one) == 1


@pytest.mark.asyncio
async def test_sessions_router_is_mounted_under_api_v1() -> None:
    """挂载断言走 OpenAPI 路径表 (``include_router`` 后的 _IncludedRouter 没有 .path)."""
    schema = app.openapi()
    paths = schema["paths"]
    assert {
        "/api/v1/sessions",
        "/api/v1/sessions/{session_id}",
        "/api/v1/sessions/{session_id}/step",
        "/api/v1/sessions/{session_id}/skip-step",
    } <= set(paths)
    assert set(paths["/api/v1/sessions"]) == {"post", "get"}
    assert set(paths["/api/v1/sessions/{session_id}"]) == {"get"}
    assert "StepAttemptResponse" in schema["components"]["schemas"]
    grade = schema["components"]["schemas"]["DrillGrade"]["properties"]
    assert {"step_id", "score", "passed", "feedback_cn", "source", "llm_source"} <= set(grade)


@pytest.mark.asyncio
async def test_stub_mode_keeps_every_grade_traceable(scene_root: Path) -> None:
    """CI 等价路径: 一路无凭据也要走到 unlock, 且每一步的来源都能被 UI 警示."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _pass_briefing(c, sid)
        body = await _snapshot(c, sid)
    assert {s["last_source"] for s in body["briefing"]["steps"]} == {"stub", "heuristic"}
    assert body["briefing"]["unlocked_mission"] is True


@pytest.mark.asyncio
async def test_llm_graded_step_reports_provenance_through_the_endpoint(
    scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """接线检查: ``llm_source`` 一路透到 API (判分口径本身在 test_drill_grader 里测)."""
    from tests.test_drill_grader import install_llm

    install_llm(monkeypatch, [json.dumps({"score": 81, "feedback_cn": "三个要点都说了。"})])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
        await _step(c, sid, "f2", audio_b64=PCM_B64)
        res = await _step(c, sid, "f3", text=PASSING_TEXT["f3"])
    grade = res.json()["grade"]
    assert grade["source"] == "llm" and grade["llm_source"] == "qwen3.8-max"
    assert grade["score"] == 81.0 and grade["passed"] is True
    assert _step_of(res.json(), "f3")["last_source"] == "llm"


@pytest.mark.asyncio
async def test_ability_events_are_computed_but_nothing_is_persisted(
    scene_root: Path, db: AsyncSession
) -> None:
    """P2 只把维度证据算给客户端 + 调 T4 的空钩子, **不写任何画像数据** (表在 M2)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        res = await _step(c, sid, "f1", audio_b64=PCM_B64)
    events = res.json()["ability_events"]
    assert events and all(e["weight"] == 0.0 for e in events)  # stub 证据门控成 0
    assert {e["dimension"] for e in events} >= {"pronunciation", "fluency"}
    tables = set(await db.run_sync(lambda sm: sa_inspect(sm.get_bind()).get_table_names()))
    assert "ability_events" not in tables and "ability_profiles" not in tables
    assert "practice_steps" in tables


@pytest.mark.asyncio
async def test_record_step_evidence_hook_is_called_per_attempt(
    scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """P3 的画像管线靠这个调用点接进去: 每落一行证据就通知一次 (P2 里它是 no-op)."""
    seen: list[dict[str, Any]] = []
    monkeypatch.setattr(
        cs,
        "record_step_evidence",
        lambda *_args, **kwargs: seen.append(kwargs),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        await _step(c, sid, "f1", audio_b64=PCM_B64)
    assert len(seen) == 1
    assert seen[0]["step_id"] == "f1" and seen[0]["session_id"] == sid
    assert seen[0]["evidence"] and seen[0]["evidence"][0].weight == 0.0


@pytest.mark.asyncio
async def test_two_sessions_of_the_same_course_progress_independently(
    scene_root: Path,
) -> None:
    """重开局不共享进度: 第二场从 f1 重新开始 (第一场的结果只留在它自己的快照里)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        one = await _open(c)
        two = await _open(c)
        await _step(c, one, "f1", audio_b64=PCM_B64)
        first = await _snapshot(c, one)
        second = await _snapshot(c, two)
    assert first["briefing"]["done"] == 1 and second["briefing"]["done"] == 0
    assert first["briefing"]["steps"][0]["last_score"] is not None
    assert second["briefing"]["steps"][0]["last_score"] is None


# ============================================================ 快照容错 (脏数据)


def test_coercion_helpers_survive_garbage() -> None:
    """快照来自 JSON 列, 可能是字符串/None/字典 —— 不能一崩就 500."""
    assert cs._as_int(None) == 0 and cs._as_int("abc") == 0 and cs._as_int("3") == 3
    assert cs._as_float(None) is None and cs._as_float("x") is None and cs._as_float("1.5") == 1.5
    assert cs._status_of("weird") == "pending" and cs._status_of("passed") == "passed"
    assert cs._truncate("a  b\n c", 50) == "a b c"
    assert cs._truncate("word " * 100, 10).endswith("…")


def test_push_event_repairs_a_missing_event_log() -> None:
    doc: dict[str, Any] = {"events": "不是列表"}
    cs._push_event(doc, "step_passed", "f1", 88.0)
    assert isinstance(doc["events"], list) and doc["events"][0]["step_id"] == "f1"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "course_value",
    [None, {"id": "scene_alpha"}, "not-a-dict"],
    ids=["missing", "invalid", "wrong-type"],
)
async def test_unusable_course_snapshot_is_a_500(
    scene_root: Path, db: AsyncSession, course_value: Any
) -> None:
    """课程快照缺/坏 -> 明确 500 SESSION_DOC_CORRUPT, 不能拿半截内容继续判分."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    row = (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalar_one()
    doc = json.loads(json.dumps(row.doc))
    if course_value is None:
        doc.pop("course")
    else:
        doc["course"] = course_value
    row.doc = doc
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})
        step = await _step(c, sid, "f1", audio_b64=PCM_B64)
    assert res.status_code == 500 and res.json()["error"]["code"] == "SESSION_DOC_CORRUPT"
    assert step.status_code == 500 and step.json()["error"]["code"] == "SESSION_DOC_CORRUPT"


@pytest.mark.asyncio
async def test_checklist_step_missing_from_the_course_is_404(
    scene_root: Path, db: AsyncSession
) -> None:
    """清单里有 step id 但课程 briefing 里没有 -> 404 STEP_NOT_FOUND (不是 500)."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
    row = (await db.execute(select(PracticeSession).where(PracticeSession.id == sid))).scalar_one()
    doc = json.loads(json.dumps(row.doc))
    doc["course"]["briefing"] = doc["course"]["briefing"][1:]  # 把 f1 从课程内容里抹掉
    row.doc = doc
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await _step(c, sid, "f1", audio_b64=PCM_B64)
    assert res.status_code == 404 and res.json()["error"]["code"] == "STEP_NOT_FOUND"


@pytest.mark.asyncio
async def test_registered_but_foreign_device_gets_403(scene_root: Path) -> None:
    """两个都已注册的设备: 拿别人的会话 id 也进不去 (走归属比对, 不是"查无此人")."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        sid = await _open(c)
        mine = await _open(c, device_id=OTHER)
        assert mine != sid
        res = await c.get(f"/api/v1/sessions/{sid}", params={"device_id": OTHER})
        step = await _step(c, sid, "f1", audio_b64=PCM_B64, device_id=OTHER)
    assert res.status_code == 403 == step.status_code
    assert step.json()["error"]["code"] == "FORBIDDEN_SESSION"


@pytest.mark.asyncio
async def test_concurrent_device_registration_falls_back_to_the_winner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``device_id`` 唯一索引上的竞争: 后到的写入者回滚后重读, 不能把 500 甩给客户端.

    两个新 device 同时首次开课时会走到这条分支 (history.py 的 _get_user 同样踩过)。
    """
    from sqlalchemy.exc import IntegrityError

    calls = {"n": 0}
    real_flush = AsyncSession.flush

    async def racing_flush(self: AsyncSession, *args: Any, **kwargs: Any) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            # 对手先落库成功
            async with get_sessionmaker()() as other:
                other.add(User(device_id="dev-race"))
                await other.commit()
            raise IntegrityError("INSERT INTO users", {}, RuntimeError("UNIQUE"))
        await real_flush(self, *args, **kwargs)

    monkeypatch.setattr(AsyncSession, "flush", racing_flush)
    async with get_sessionmaker()() as db:
        user = await cs._get_or_create_user(db, "dev-race")
    assert user.device_id == "dev-race"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_create_session_accepts_user_id_identity(scene_root: Path, db: AsyncSession) -> None:
    """``user_id`` 也能开课 (P4 的生成课按 user 归属, 客户端可能只有 user_id)."""
    user = User(device_id="dev-by-user")
    db.add(user)
    await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        res = await c.post(
            "/api/v1/sessions",
            json={"user_id": user.id, "kind": "scene_course", "scene_id": "scene_alpha"},
        )
        assert res.status_code == 201, res.text
        unknown = await c.post(
            "/api/v1/sessions",
            json={"user_id": "00000000-0000-0000-0000-000000000000", "scene_id": "scene_alpha"},
        )
        listed = await c.get("/api/v1/sessions", params={"user_id": user.id})
    body = res.json()
    row = (
        await db.execute(select(PracticeSession).where(PracticeSession.id == body["session_id"]))
    ).scalar_one()
    assert row.user_id == user.id and row.owner_device_id == "dev-by-user"
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "USER_NOT_FOUND"
    assert [i["session_id"] for i in listed.json()] == [body["session_id"]]
