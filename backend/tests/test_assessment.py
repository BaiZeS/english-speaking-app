"""CEFR 摸底测评 (P4) 测试: 题库契约 / start-answer-complete 全流程 / 写入门控.

任务书 §范围 4 + §范围 5 的核心断言:

* 真题库 7 题人工编写: 题型分布 (跟读x2 复述x1 翻译x1 开放问答x2 快答x1)、
  A2-B1 梯度、每题带 ref/参考要点/CEFR 锚; 客户端摘要**不下发**参考要点;
* answer: 文本直给; 音频非跟读走 IAT (无凭据 400 TRANSCRIPT_UNAVAILABLE);
  跟读走 ISE —— **真实 ISE 才落 ise_score**, stub 占位分不落库; 重答覆盖;
* complete stub (LLM 未配置): 结果照常返回但 cefr/维度 null + **零事件零画像**
  (诚实空态); 有真实 ISE 时发音维只读不写;
* complete 真 LLM: 一次批量判级 -> ``ability_events`` (source_kind=assessment,
  w=1) + 画像四维种子/**alpha=0.6 重拉** + ``assessment_cefr`` + ``band_locked`` +
  ``cefr_level=resolve_level``; 幂等重放不再调 LLM;
* 归属: attempt 404 / 403 可区分; 题库坏文件 -> 空题库 + start 503。

autouse 夹具复位 llm provider 单例 (任务书 §范围 5 的硬要求)。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.db import AbilityEvent, AbilityProfile, AssessmentAnswer, AssessmentAttempt, User
from app.services import assessment_engine
from app.services import drill_grader as dg
from app.services.ability_engine import ALPHA
from tests.test_drill_grader import FakeASR, install_llm

DEV = "dev-assess"
OTHER = "dev-assess-other"
PCM_B64 = base64.b64encode(b"\x00\x01" * 3200).decode()


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    from app.services import llm_provider

    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


def judgement_json(
    cefr: str = "B1", grammar: float = 72.0, vocabulary: float = 65.0, fluency: float = 58.0
) -> str:
    return json.dumps(
        {
            "cefr": cefr,
            "grammar": grammar,
            "vocabulary": vocabulary,
            "fluency": fluency,
            "rationale_cn": "定级 B1。A2 题全部达意, B1 复述少了两个要点。语法时态偶错, 先练过去时叙事。",
        },
        ensure_ascii=False,
    )


async def _start(client: AsyncClient, device: str = DEV) -> str:
    res = await client.post("/api/v1/assessment/start", json={"device_id": device})
    assert res.status_code == 201, res.text
    return str(res.json()["attempt_id"])


async def _answer(client: AsyncClient, attempt_id: str, **body: Any) -> Any:
    payload: dict[str, Any] = {
        "device_id": DEV,
        "question_no": 4,
        "text": "I start my new job next Monday.",
    }
    payload.update(body)
    return await client.post(f"/api/v1/assessment/{attempt_id}/answer", json=payload)


# ============================================================ 题库契约


def test_real_bank_contract() -> None:
    questions = assessment_engine.load_bank()
    assert len(questions) == 7
    types = sorted(q.type for q in questions)
    assert types == [
        "open_question",
        "open_question",
        "quick_chat",
        "read_aloud",
        "read_aloud",
        "retell",
        "translate",
    ]
    assert [q.no for q in questions] == list(range(1, 8))
    anchors = {q.cefr_anchor for q in questions}
    assert anchors <= {"A2", "B1"} and "B1" in anchors and "A2" in anchors  # A2-B1 梯度
    for q in questions:
        assert q.ref_text.strip() and q.cn_prompt.strip()
        assert q.key_points and all(kp.strip() for kp in q.key_points)  # 每题有参考要点


@pytest.mark.asyncio
async def test_get_bank_hides_reference_material(client: AsyncClient) -> None:
    res = await client.get("/api/v1/assessment")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 7 and len(body["questions"]) == 7
    first = body["questions"][0]
    assert {"id", "no", "type", "cn_prompt", "display_text", "cefr_anchor", "seconds"} <= (
        set(first)
    )
    assert "key_points" not in first  # 参考要点永不下发
    assert "reference_answer" not in first


@pytest.mark.asyncio
async def test_bad_bank_degrades_to_empty(
    client: AsyncClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(assessment_engine, "_BANK_ROOT", tmp_path)  # 空目录 = 题库缺失
    res = await client.get("/api/v1/assessment")
    assert res.status_code == 200 and res.json()["total"] == 0
    start = await client.post("/api/v1/assessment/start", json={"device_id": DEV})
    assert (
        start.status_code == 503 and start.json()["error"]["code"] == "ASSESSMENT_BANK_UNAVAILABLE"
    )


# ============================================================ start / answer


@pytest.mark.asyncio
async def test_start_creates_attempt(client: AsyncClient, db: AsyncSession) -> None:
    res = await client.post("/api/v1/assessment/start", json={"device_id": DEV})
    assert res.status_code == 201
    body = res.json()
    assert body["total"] == 7 and body["attempt_id"]
    row = (
        await db.execute(
            select(AssessmentAttempt).where(AssessmentAttempt.id == body["attempt_id"])
        )
    ).scalar_one()
    assert row.status == "running" and row.answers_count == 0 and row.result is None
    user = (await db.execute(select(User).where(User.device_id == DEV))).scalar_one()
    assert row.user_id == user.id


@pytest.mark.asyncio
async def test_answer_text_and_reanswer_overwrites(client: AsyncClient, db: AsyncSession) -> None:
    attempt_id = await _start(client)
    res = await _answer(client, attempt_id, question_no=4)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["answers_count"] == 1 and body["total"] == 7
    assert body["transcript"].startswith("I start")

    # 重答 = 覆盖 (answers_count 不涨)
    res2 = await _answer(client, attempt_id, question_no=4, text="My new job starts next Monday.")
    assert res2.json()["answers_count"] == 1
    rows = (
        (
            await db.execute(
                select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id)
            )
        )
        .scalars()
        .all()
    )
    assert len(rows) == 1 and rows[0].transcript.startswith("My new job")


@pytest.mark.asyncio
async def test_answer_gates(client: AsyncClient, db: AsyncSession) -> None:
    attempt_id = await _start(client)
    other_attempt = await _start(client, device=OTHER)

    res = await _answer(client, attempt_id, question_no=99)
    assert res.status_code == 404 and res.json()["error"]["code"] == "QUESTION_NOT_FOUND"
    res = await _answer(client, "no-such-attempt", question_no=1)
    assert res.status_code == 404 and res.json()["error"]["code"] == "ATTEMPT_NOT_FOUND"
    res = await _answer(client, other_attempt, question_no=1, text="hi")
    assert res.status_code == 403 and res.json()["error"]["code"] == "FORBIDDEN_ATTEMPT"
    res = await _answer(client, attempt_id, question_no=1, text=None)  # 无 text 无 audio
    assert res.status_code == 400 and res.json()["error"]["code"] == "ASSESSMENT_ANSWER_REQUIRED"

    # 空答案 + 无凭据音频 (开放问答走 IAT) -> 400 TRANSCRIPT_UNAVAILABLE
    res = await _answer(client, attempt_id, question_no=5, text=None, audio_b64=PCM_B64)
    assert res.status_code == 400 and res.json()["error"]["code"] == "TRANSCRIPT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_answer_after_complete_is_conflict(client: AsyncClient) -> None:
    attempt_id = await _start(client)
    await _answer(client, attempt_id)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 200
    res = await _answer(client, attempt_id, question_no=5, text="Sure.")
    assert res.status_code == 409 and res.json()["error"]["code"] == "ATTEMPT_NOT_ACTIVE"


@pytest.mark.asyncio
async def test_read_aloud_stub_ise_stores_nothing(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跟读 + stub ISE: 恒 95 是占位 -> ise_score 不落库 (发音维宁缺勿滥)."""
    monkeypatch.setattr(dg, "_ISE", FakeASR(scores=95.0, source="stub"))
    attempt_id = await _start(client)
    res = await _answer(client, attempt_id, question_no=1, text=None, audio_b64=PCM_B64)
    assert res.status_code == 200
    assert res.json()["transcript"] == ""
    row = (
        await db.execute(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id))
    ).scalar_one()
    assert row.ise_score is None and row.speech_rate_wpm is None and row.transcript == ""


@pytest.mark.asyncio
async def test_read_aloud_real_ise_stores_score(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跟读 + 真实 ISE: 分数/转写/语速都落库 (发音维的唯一证据来源)."""
    monkeypatch.setattr(dg, "_ISE", FakeASR(scores=80.0, source="xunfei"))
    attempt_id = await _start(client)
    res = await _answer(client, attempt_id, question_no=1, text=None, audio_b64=PCM_B64)
    assert res.status_code == 200
    assert res.json()["transcript"].startswith("I usually take the subway")
    row = (
        await db.execute(select(AssessmentAnswer).where(AssessmentAnswer.attempt_id == attempt_id))
    ).scalar_one()
    assert row.ise_score == pytest.approx(80.0)
    assert row.speech_rate_wpm and row.speech_rate_wpm > 0


# ============================================================ complete: stub 诚实空态


@pytest.mark.asyncio
async def test_complete_requires_answers(client: AsyncClient) -> None:
    attempt_id = await _start(client)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 400 and res.json()["error"]["code"] == "ASSESSMENT_NO_ANSWERS"


@pytest.mark.asyncio
async def test_complete_stub_zero_writes(client: AsyncClient, db: AsyncSession) -> None:
    """LLM 未配置: 结果返回但 cefr/维度全 null, **零事件、零画像** (诚实空态)."""
    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=4)
    await _answer(client, attempt_id, question_no=5, text="I usually watch movies and cook.")

    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "stub" and body["llm_source"] == "stub"
    assert body["cefr"] is None and body["cefr_level"] is None
    assert body["dims"] == {
        "pronunciation": None,
        "grammar": None,
        "vocabulary": None,
        "fluency": None,
    }
    assert body["pronunciation_source"] is None
    assert "未配置" in body["rationale_cn"]

    assert (await db.execute(select(func.count()).select_from(AbilityEvent))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(AbilityProfile))).scalar_one() == 0

    attempt = (
        await db.execute(select(AssessmentAttempt).where(AssessmentAttempt.id == attempt_id))
    ).scalar_one()
    assert attempt.status == "completed" and attempt.result is not None
    assert attempt.finished_at is not None

    # 幂等: 再 complete 回放同一结果
    again = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert again.status_code == 200 and again.json()["cefr"] is None


@pytest.mark.asyncio
async def test_complete_stub_with_real_ise_still_zero_events(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """任务书门控: llm_source=stub -> **不落 events**; 发音分只回显不写画像."""
    monkeypatch.setattr(dg, "_ISE", FakeASR(scores=80.0, source="xunfei"))
    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=1, text=None, audio_b64=PCM_B64)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    body = res.json()
    assert body["source"] == "stub"
    assert body["dims"]["pronunciation"] == pytest.approx(80.0)  # 真实 ISE 证据回显
    assert body["pronunciation_source"] == "ise"
    assert (await db.execute(select(func.count()).select_from(AbilityEvent))).scalar_one() == 0
    assert (await db.execute(select(func.count()).select_from(AbilityProfile))).scalar_one() == 0


@pytest.mark.asyncio
async def test_complete_ownership_gates(client: AsyncClient) -> None:
    attempt_id = await _start(client)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": OTHER})
    assert res.status_code == 403
    res = await client.post("/api/v1/assessment/no-such/complete", json={"device_id": DEV})
    assert res.status_code == 404


# ============================================================ complete: 真判级写画像


@pytest.mark.asyncio
async def test_complete_with_llm_writes_profile_gated(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_llm(monkeypatch, [judgement_json()])
    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=4)
    await _answer(
        client,
        attempt_id,
        question_no=6,
        text="Last month the server crashed, I restarted it and we lost no data.",
    )

    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["source"] == "llm" and body["llm_source"] == "qwen3.8-max"
    assert body["cefr"] == "B1"
    assert body["dims"] == {
        "pronunciation": None,  # 没有真实 ISE -> 发音维 null (不虚构)
        "grammar": 72.0,
        "vocabulary": 65.0,
        "fluency": 58.0,
    }
    assert body["cefr_level"] == "B1"  # resolve_level: 四维均值 65 -> B1, 锁带后仍是 B1
    assert "B1" in body["rationale_cn"]

    # 事件流水: source_kind=assessment, w=1 (三门), 发音无证据不出事件
    events = (
        (
            await db.execute(
                select(AbilityEvent).where(AbilityEvent.user_id == await _uid_of(db, DEV))
            )
        )
        .scalars()
        .all()
    )
    assert sorted(e.dimension for e in events) == ["fluency", "grammar", "vocabulary"]
    assert all(e.source_kind == "assessment" and e.weight == 1.0 for e in events)

    # 画像: 首条证据种子化 + assessment_cefr + band_locked + 权威 cefr_level
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.grammar == 72.0 and profile.vocabulary == 65.0 and profile.fluency == 58.0
    assert profile.pronunciation is None
    assert profile.assessment_cefr == "B1" and profile.band_locked is True
    assert profile.cefr_level == "B1"

    # 判级恰好 1 次调用; 幂等重放不再调 LLM
    assert len(fake.requests) == 1
    prompt = str(fake.requests[0]["messages"][1]["content"])
    assert "I start my new job next Monday." in prompt  # 作答全部进 prompt
    again = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert again.status_code == 200 and again.json()["cefr"] == "B1"
    assert len(fake.requests) == 1


@pytest.mark.asyncio
async def test_assessment_alpha_is_six_tenths(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """任务书钉死的 alpha=0.6: 已有画像 50 -> 判级 80 -> 50*0.4 + 80*0.6 = 68."""
    install_llm(monkeypatch, [judgement_json(grammar=80.0, vocabulary=80.0, fluency=80.0)])
    user = User(device_id=DEV)
    db.add(user)
    await db.flush()
    db.add(AbilityProfile(user_id=user.id, grammar=50.0, grammar_n=1))
    await db.commit()

    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=4)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 200
    profile = (
        await db.execute(select(AbilityProfile).where(AbilityProfile.user_id == user.id))
    ).scalar_one()
    assert profile.grammar == pytest.approx(68.0)  # 0.4*50 + 0.6*80
    assert profile.vocabulary == pytest.approx(80.0)  # 首条证据种子化
    assert ALPHA["grammar"] == 0.2  # 常规口径不动 (判级时才覆写)


async def _uid_of(db: AsyncSession, device_id: str) -> str:
    return str(
        ((await db.execute(select(User).where(User.device_id == device_id))).scalar_one()).id
    )


def test_ability_events_from_judgement_is_honest_about_none() -> None:
    """stub 判级 (None) 不产任何事件; 发音只有真实 ISE 才产事件."""
    assert assessment_engine.ability_events_from_judgement(None, 80.0) == []
    events = assessment_engine.ability_events_from_judgement(
        assessment_engine.Judgement(
            cefr="A2", grammar=60.0, vocabulary=60.0, fluency=60.0, rationale_cn="ok"
        ),
        None,
    )
    assert sorted(d for d, _s in events) == ["fluency", "grammar", "vocabulary"]


@pytest.mark.asyncio
async def test_bank_not_an_object_degrades_to_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "assessment").mkdir()
    (tmp_path / "assessment" / "bank.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(assessment_engine, "_BANK_ROOT", tmp_path)
    assert assessment_engine.load_bank() == []


@pytest.mark.asyncio
async def test_bank_duplicate_numbers_keep_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real = json.loads(Path("data/assessment/bank.json").read_text(encoding="utf-8"))
    real["questions"].append(dict(real["questions"][0]))  # 同 no 两题 -> 保留先出现的
    (tmp_path / "assessment").mkdir()
    (tmp_path / "assessment" / "bank.json").write_text(json.dumps(real), encoding="utf-8")
    monkeypatch.setattr(assessment_engine, "_BANK_ROOT", tmp_path)
    questions = assessment_engine.load_bank()
    assert len(questions) == 7 and len({q.no for q in questions}) == 7


@pytest.mark.asyncio
async def test_judgement_invalid_cefr_retries_then_writes(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判级第一把 cefr 非法 -> 校验错误回喂重试 -> 第二把好 (画像照写)."""
    fake = install_llm(monkeypatch, [judgement_json(cefr="B9"), judgement_json()])
    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=4)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    assert res.status_code == 200 and res.json()["cefr"] == "B1"
    assert len(fake.requests) == 2
    assert "cefr" in str(fake.requests[1]["messages"][-1]["content"])
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.assessment_cefr == "B1"


@pytest.mark.asyncio
async def test_complete_real_ise_plus_llm_writes_pronunciation_event(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """真实 ISE + 真 LLM: 发音维事件 (exact_reference) 一并入库, 四维齐全."""
    monkeypatch.setattr(dg, "_ISE", FakeASR(scores=80.0, source="xunfei"))
    install_llm(monkeypatch, [judgement_json(grammar=70.0, vocabulary=70.0, fluency=70.0)])
    attempt_id = await _start(client)
    await _answer(client, attempt_id, question_no=1, text=None, audio_b64=PCM_B64)
    await _answer(client, attempt_id, question_no=4)
    res = await client.post(f"/api/v1/assessment/{attempt_id}/complete", json={"device_id": DEV})
    body = res.json()
    assert body["dims"]["pronunciation"] == pytest.approx(80.0)
    assert body["pronunciation_source"] == "ise"
    events = (
        (
            await db.execute(
                select(AbilityEvent).where(AbilityEvent.user_id == await _uid_of(db, DEV))
            )
        )
        .scalars()
        .all()
    )
    assert sorted(e.dimension for e in events) == [
        "fluency",
        "grammar",
        "pronunciation",
        "vocabulary",
    ]
    pron = next(e for e in events if e.dimension == "pronunciation")
    assert pron.score == pytest.approx(80.0) and pron.ise_ref_mode == "exact_reference"
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.pronunciation == pytest.approx(80.0)


@pytest.mark.asyncio
async def test_start_and_answer_require_identity(client: AsyncClient) -> None:
    attempt_id = await _start(client)
    res = await client.post("/api/v1/assessment/start", json={})
    assert res.status_code == 400 and res.json()["error"]["code"] == "IDENTITY_REQUIRED"
    res = await client.post(
        f"/api/v1/assessment/{attempt_id}/answer", json={"question_no": 4, "text": "hi"}
    )
    assert res.status_code == 400 and res.json()["error"]["code"] == "IDENTITY_REQUIRED"


@pytest.mark.asyncio
async def test_bank_missing_questions_key_degrades_to_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "assessment").mkdir()
    (tmp_path / "assessment" / "bank.json").write_text('{"version": 1}', encoding="utf-8")
    monkeypatch.setattr(assessment_engine, "_BANK_ROOT", tmp_path)
    assert assessment_engine.load_bank() == []
