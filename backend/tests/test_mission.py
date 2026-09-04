"""实战对话 (mission) + 复盘报告 端点测试 (§5.3/§5.5-2/§5.6, 阶段 P3).

按"客户端会怎么踩"组织:

* 打完基础 -> ``/mission`` 逐轮 (mock LLM 的综合 JSON) -> 任务累积打勾 -> cleared ->
  ``/finish-mission`` 出 ReviewReport -> 报告持久化 + history 落行 (老历史页形状);
* 门禁可区分: 阶段未解锁 / 归属 / 收工后的 409 各不相同, 越权 403;
* 任务状态**累积合并** + 幂等 (同一段话连说两轮不重复打勾; LLM 翻供不回退);
* LLM 坏 JSON -> 回喂重试一次 -> 再坏走剧本回放的确定性降级 (``source=heuristic``,
  ``llm_source=stub``); 降级轮**不出**语法/词汇证据 (宁缺勿滥);
* ``max_turns`` 到顶自动收工 (报告随最后一轮返回, 会话 ``review/completed``);
* 讯飞路径: 音频缺 IAT -> 400 TRANSCRIPT_UNAVAILABLE; ISE 配了才产
  ``transcript_anchored`` 发音证据; ISE 失败回退 stub 时证据**整体丢弃**;
* ``/hint`` 不调 LLM、不改判定, 只把下一个判定回合标 ``costs_score``.

Mock 手法沿用 T3 (``tests.test_drill_grader``): ``install_llm`` 换掉 ``AsyncOpenAI``
并按脚本吐 content; 本文件自带 **autouse** provider 复位 —— 漏了会把"LLM 已配置"
泄漏给后面的模块 (``test_dialogue_stub`` 那批断言会莫名变红, T3 踩过)。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.main import app
from app.models.db import AbilityEvent, AbilityProfile, AnnotatedDiff, History, PracticeStep
from app.services import drill_grader as dg
from app.services import llm_provider, scene_store
from app.services import mission_engine as me
from tests.test_course_sessions import BRIEFING6, _pass_briefing
from tests.test_drill_grader import FakeASR, FakeIAT, install_llm
from tests.test_scene_store import make_course_dict, write_course

DEV = "dev-session"  # 与 test_course_sessions 的 helper 共用身份 (_pass_briefing 写死了它)
PCM_B64 = base64.b64encode(b"\x00\x01" * 3200).decode()  # 200ms 假 PCM


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def scene_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    write_course(tmp_path, "scene_alpha", "daily", briefing=BRIEFING6)
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()
    yield tmp_path  # type: ignore[misc]
    scene_store.invalidate_cache()


def mission_json(
    *,
    reply: str = "How about a size? We have small and large.",
    suggestion: str = "Can I change that to a large?",
    polish: dict[str, Any] | None = None,
    grammar: float | None = 66.0,
    vocabulary: float | None = 70.0,
    done: list[tuple[str, str]] | None = None,
) -> str:
    """一轮的综合 JSON (§5.5-2 形状)."""
    return json.dumps(
        {
            "reply": reply,
            "suggestion": suggestion,
            "polish": polish,
            "grammar_score": grammar,
            "vocabulary_score": vocabulary,
            "task_progress": [
                {"id": task_id, "done": True, "evidence": evidence}
                for task_id, evidence in (done or [])
            ],
        },
        ensure_ascii=False,
    )


async def _open(client: AsyncClient, scene_id: str = "scene_alpha") -> str:
    res = await client.post(
        "/api/v1/sessions",
        json={"device_id": DEV, "kind": "scene_course", "scene_id": scene_id},
    )
    assert res.status_code == 201, res.text
    return str(res.json()["session_id"])


async def _ready(client: AsyncClient) -> str:
    """开好局并把打基础全做完 (无凭据 -> 启发式/stub, 画像不动, 与 mission 解耦)."""
    sid = await _open(client)
    await _pass_briefing(client, sid)
    return sid


async def _mission(client: AsyncClient, sid: str, payload: dict[str, Any]) -> Any:
    body = {"device_id": DEV, **payload}
    return await client.post(f"/api/v1/sessions/{sid}/mission", json=body)


# ============================================================ 阶段门禁


@pytest.mark.asyncio
async def test_mission_before_briefing_is_wrong_stage(
    client: AsyncClient, scene_root: Path
) -> None:
    sid = await _open(client)
    res = await _mission(client, sid, {"text": "A medium coffee please."})
    assert res.status_code == 409 and res.json()["error"]["code"] == "WRONG_STAGE"


# ============================================================ happy path (mock LLM)


@pytest.mark.asyncio
async def test_mission_loop_clears_tasks_and_finishes_with_report(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    sid = await _ready(client)  # 先打完基础 (启发式), 再装假 LLM, 免得判分吃掉剧本回复
    fake = install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "说了点单内容")]),
            mission_json(
                done=[("t1", "说了点单内容"), ("t2", "问了价格")],
                polish={
                    "original": "How much money?",
                    "polished": "How much is that in total?",
                    "explanation_cn": "问价格说 how much is that。",
                },
            ),
            json.dumps(
                {
                    "highlights": ["点单和问价都当面说出口了, 沟通目的达成。"],
                    "improvements": ["语法: 特殊疑问句的语序再练一轮。"],
                },
                ensure_ascii=False,
            ),
        ],
    )

    first = await _mission(client, sid, {"text": "Can I get a medium coffee?"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["turn_index"] == 1 and body["transcript"] == "Can I get a medium coffee?"
    assert body["reply"].startswith("How about") and body["suggestion"]
    assert body["polish"] is None and body["cleared"] is False
    assert body["newly_done"] == [{"id": "t1", "evidence": "说了点单内容"}]
    assert [view["done"] for view in body["checklist"]] == [True, False, False]
    assert body["sub_scores"] == {
        "pronunciation": None,
        "grammar": 66.0,
        "vocabulary": 70.0,
        "fluency": None,
    }  # 没配讯飞: 发音/流利没有证据, 不冒充 (§5.6)
    assert body["max_turns"] == 8 and body["source"] == "llm"
    assert body["llm_source"] == "qwen3.8-max" and body["costs_score"] is False
    grammar_event = next(e for e in body["ability_events"] if e["dimension"] == "grammar")
    assert grammar_event["weight"] == 1.0 and grammar_event["source"] == "llm"

    second = (await _mission(client, sid, {"text": "How much money?"})).json()
    assert second["turn_index"] == 2 and second["cleared"] is True
    assert second["newly_done"] == [{"id": "t2", "evidence": "问了价格"}]
    assert second["polish"]["polished"] == "How much is that in total?"
    optional_task = next(view for view in second["checklist"] if view["id"] == "t3")
    assert optional_task["required"] is False and optional_task["done"] is False

    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert finish.status_code == 200, finish.text
    report = finish.json()["report"]
    assert finish.json()["stage"] == "review" and finish.json()["status"] == "completed"

    assert report["cleared"] is True and report["auto_finished"] is False
    assert report["turn_count"] == 2 and report["max_turns"] == 8
    assert report["dims"]["grammar"] == pytest.approx(66.0)  # 只聚合可信来源 (启发式 100 不掺)
    assert report["dims"]["vocabulary"] == pytest.approx(70.0)
    assert report["dims"]["pronunciation"] is None  # 全程没有真 ISE 证据 != stub 的假 95
    assert report["overall"] == pytest.approx(68.0)
    assert report["pronunciation_subs"]["pronunciation"] is None  # 连读行是 stub -> 不计
    assert report["highlights"] == ["点单和问价都当面说出口了, 沟通目的达成。"]
    assert report["improvements"] == ["语法: 特殊疑问句的语序再练一轮。"]
    assert [view["done"] for view in report["checklist"]] == [True, True, False]
    assert report["transcript_pairs"] and report["transcript_pairs"][0]["polished"] == (
        "How much is that in total?"
    )
    assert report["transcript_pairs"][0]["source"] == "mission"
    assert set(report["new_tokens"]) >= {"order", "sugar"}  # 转写里真说过的核心词
    # 开局基线全 None (本机 brief 轮全被门控) -> 拉动不可知 -> None, 别拿 0 冒充
    assert report["ability_delta"] == {
        "pronunciation": None,
        "grammar": None,
        "vocabulary": None,
        "fluency": None,
    }
    assert report["source"] == "llm" and report["llm_source"] == "qwen3.8-max"
    assert fake.requests[-1]["model"] == "qwen3.8-max"  # 复盘文案也是服务端默认模型

    steps = (
        (await db.execute(select(PracticeStep).where(PracticeStep.session_id == sid)))
        .scalars()
        .all()
    )
    mission_rows = sorted(
        (s for s in steps if s.step_type == "mission_turn"), key=lambda s: s.step_id
    )
    assert [s.step_id for s in mission_rows] == ["m1", "m2"]
    assert mission_rows[0].ok is True and mission_rows[0].transcript  # ok = 本轮推进了任务
    assert mission_rows[0].score_grammar == 66.0 and mission_rows[0].score_pronunciation is None
    assert mission_rows[1].annotated_json["polish"]["original"] == "How much money?"
    events = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id.in_(["m1", "m2"])
                )
            )
        )
        .scalars()
        .all()
    )
    assert {(e.dimension, e.weight, e.source_kind) for e in events} == {
        ("grammar", 1.0, "llm"),
        ("vocabulary", 1.0, "llm"),
    }
    gated = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id.in_(["f1", "f4"])
                )
            )
        )
        .scalars()
        .all()
    )  # 打基础的 stub/heuristic 证据也进了流水 (w=0, 审计用)
    assert gated and all(e.weight == 0.0 for e in gated)
    profiles = (await db.execute(select(AbilityProfile))).scalars().all()
    assert len(profiles) == 1 and profiles[0].grammar == pytest.approx(66.0)  # 种子化首样本
    assert profiles[0].cefr_level is None  # 测评 (P4) 之前权威 CEFR 恒 null
    diffs = (await db.execute(select(AnnotatedDiff))).scalars().all()
    assert [(d.origin, d.polished) for d in diffs] == [("mission", "How much is that in total?")]
    history_rows = (await db.execute(select(History))).scalars().all()
    assert len(history_rows) == 1
    row = history_rows[0]
    assert row.book == "scenes" and row.line_id == sid and row.audio_path == "scene_alpha"
    assert 0 < row.lesson_id < 100_000_000  # script_lesson_no 稳定散列, (book, lesson) 聚合可玩
    assert row.score_total == pytest.approx(report["overall"])

    # 收工后一切可变端点被挡; 崩溃恢复快照带 review
    late = await _mission(client, sid, {"text": "one more"})
    assert late.status_code == 409 and late.json()["error"]["code"] == "SESSION_NOT_ACTIVE"
    finish_again = await client.post(
        f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV}
    )
    assert finish_again.status_code == 409
    snapshot = (await client.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})).json()
    assert snapshot["stage"] == "review" and snapshot["review"]["session_id"] == sid
    assert snapshot["mission"]["finished"] is True and snapshot["mission"]["turn_count"] == 2
    assert snapshot["mission"]["opening"]["a"] == "Hi, what can I get you?"


@pytest.mark.asyncio
async def test_cleared_mission_keeps_talking_until_finish(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """通关后不封麦: 学员可以继续聊, 直到 finish-mission 才收工 (P6 的聊天体验)."""
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "x"), ("t2", "y")]),
            mission_json(done=[], reply="Have a good day!"),
        ],
    )
    cleared_turn = (await _mission(client, sid, {"text": "Coffee. How much?"})).json()
    assert cleared_turn["cleared"] is True
    extra = await _mission(client, sid, {"text": "Thanks, you too!"})
    assert extra.status_code == 200 and extra.json()["cleared"] is True


# ============================================================ 累积合并 / 幂等


@pytest.mark.asyncio
async def test_same_utterance_twice_does_not_double_count_task(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "a")]),
            mission_json(done=[("t1", "a")]),
            mission_json(done=[("t1", "a"), ("t2", "b")]),
        ],
    )
    first = (await _mission(client, sid, {"text": "Medium coffee please."})).json()
    repeat = (await _mission(client, sid, {"text": "Medium coffee please."})).json()
    third = (await _mission(client, sid, {"text": "How much total?"})).json()
    assert first["newly_done"] == [{"id": "t1", "evidence": "a"}]
    assert repeat["newly_done"] == [] and repeat["turn_index"] == 2  # 同句重说不重复打勾
    assert third["newly_done"] == [{"id": "t2", "evidence": "b"}] and third["cleared"] is True


@pytest.mark.asyncio
async def test_task_completion_is_sticky_when_llm_walks_it_back(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """累积口径 (§5.5-2): 防误标后无法回退 —— LLM 翻供也不撤已打的勾."""
    sid = await _ready(client)
    install_llm(
        monkeypatch,
        [
            mission_json(done=[("t1", "ok")]),
            json.dumps(
                {
                    "reply": "r",
                    "suggestion": "s",
                    "polish": None,
                    "grammar_score": 5,
                    "vocabulary_score": 5,
                    "task_progress": [{"id": "t1", "done": False, "evidence": ""}],
                }
            ),
        ],
    )
    await _mission(client, sid, {"text": "Coffee please."})
    second = (await _mission(client, sid, {"text": "er"})).json()
    assert second["checklist"][0]["done"] is True and second["newly_done"] == []


@pytest.mark.asyncio
async def test_hallucinated_task_ids_are_dropped(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    install_llm(monkeypatch, [mission_json(done=[("t99", "不存在")])])
    body = (await _mission(client, sid, {"text": "hi there."})).json()
    assert body["newly_done"] == []
    assert [view["id"] for view in body["checklist"]] == ["t1", "t2", "t3"]


# ============================================================ 降级 / 坏 JSON


@pytest.mark.asyncio
async def test_bad_json_retries_once_then_uses_the_good_reply(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    fake = install_llm(monkeypatch, ["这不是 JSON", mission_json(done=[("t1", "救回来了")])])
    body = (await _mission(client, sid, {"text": "Medium coffee."})).json()
    assert len(fake.requests) == 2  # 初次 + 错误回喂重试一次
    assert body["source"] == "llm" and body["newly_done"] == [{"id": "t1", "evidence": "救回来了"}]
    assert "上一条输出不合格" in str(fake.requests[1]["messages"][-1]["content"])


@pytest.mark.asyncio
async def test_second_bad_output_degrades_to_script_replay(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sid = await _ready(client)
    fake = install_llm(monkeypatch, ["garbage one", "garbage two"])
    body = (await _mission(client, sid, {"text": "Medium coffee with cream please."})).json()
    assert len(fake.requests) == 2  # 只重试一次, 不做第三次
    assert body["source"] == "heuristic" and body["llm_source"] == "stub"
    assert body["reply"] == "Hi, what can I get you?"  # 参考剧本 A 行 (确定性回放, 不冒充生成)
    assert body["suggestion"] == "A small coffee, please."  # 剧本 B 行当示范
    assert body["polish"] is None
    assert body["sub_scores"]["grammar"] is None  # 降级轮不出语法/词汇证据 (宁缺勿滥)
    assert body["ability_events"] == []


@pytest.mark.asyncio
async def test_no_llm_creds_run_the_loop_on_heuristic_task_matching(
    client: AsyncClient,
    scene_root: Path,
) -> None:
    """本机/CI (只有 stub 凭据): hint_en 词面覆盖推进任务, 画像全程不动."""
    sid = await _ready(client)
    first = (await _mission(client, sid, {"text": "A small coffee, please."})).json()
    assert first["source"] == "heuristic" and first["llm_source"] == "stub"
    assert first["newly_done"] and first["newly_done"][0]["id"] == "t1"
    assert first["ability_events"] == []
    off = (await _mission(client, sid, {"text": "The weather is nice today."})).json()
    assert off["newly_done"] == []
    second = (await _mission(client, sid, {"text": "How much is that?"})).json()
    assert second["cleared"] is True  # t2 的 hint_en 就是这句话
    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    report = finish.json()["report"]
    assert report["source"] == "heuristic" and report["llm_source"] == "stub"
    assert report["cleared"] is True and report["highlights"] and report["improvements"]
    assert report["ability_delta"]["grammar"] is None


@pytest.mark.asyncio
async def test_heuristic_and_stub_evidence_never_creates_a_profile(
    client: AsyncClient, scene_root: Path, db: AsyncSession
) -> None:
    """§四 决策表的硬验收: 本机 (讯飞/LLM 都没 key) 画像永远不动."""
    sid = await _ready(client)
    await _mission(client, sid, {"text": "A small coffee, please."})
    await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    events = (await db.execute(select(AbilityEvent))).scalars().all()
    assert events  # 打基础的 stub/heuristic 证据全量进了流水 (审计)
    assert all(e.weight == 0.0 for e in events)
    assert (await db.execute(select(AbilityProfile))).scalars().all() == []


# ============================================================ max_turns 自动收工


@pytest.mark.asyncio
async def test_max_turns_cap_auto_finishes_with_report(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: AsyncClient,
) -> None:
    payload = make_course_dict()
    payload["briefing"] = BRIEFING6  # 与 _pass_briefing helper 的步骤清单一致
    mission = dict(payload["mission"])
    mission["max_turns"] = 4
    payload["mission"] = mission
    root = tmp_path / "scenes"
    root.mkdir(parents=True, exist_ok=True)
    (root / "scene_alpha.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    monkeypatch.setattr(scene_store, "_CORPUS_ROOT", tmp_path)
    scene_store.invalidate_cache()

    sid = await _ready(client)
    for i in range(1, 4):
        body = (await _mission(client, sid, {"text": f"turn number {i} content"})).json()
        assert body["auto_finished"] is False and body["review"] is None
    last = (await _mission(client, sid, {"text": "turn number four!"})).json()
    assert last["turn_count"] == 4 and last["auto_finished"] is True and last["finished"] is True
    assert last["stage"] == "review" and last["status"] == "completed"
    assert last["review"] is not None and last["review"]["auto_finished"] is True
    assert last["review"]["cleared"] is False  # 到顶未尽 -> 按未通关收口 (§5.1)

    snapshot = (await client.get(f"/api/v1/sessions/{sid}", params={"device_id": DEV})).json()
    assert snapshot["stage"] == "review" and snapshot["status"] == "completed"
    assert snapshot["review"]["session_id"] == sid


# ============================================================ 音频输入 / 转写锚定 ISE


@pytest.mark.asyncio
async def test_audio_mission_without_iat_is_400(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    res = await _mission(client, sid, {"audio_b64": PCM_B64})
    assert res.status_code == 400 and res.json()["error"]["code"] == "TRANSCRIPT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_mission_without_any_input_is_400(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    res = await _mission(client, sid, {})
    assert res.status_code == 400 and res.json()["error"]["code"] == "MISSION_INPUT_REQUIRED"


@pytest.mark.asyncio
async def test_audio_mission_uses_transcription_and_text_wins_over_audio(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    iat = FakeIAT("A small coffee to go.")
    monkeypatch.setattr(dg, "_IAT", iat)
    sid = await _ready(client)
    by_audio = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert by_audio["transcript"] == "A small coffee to go."
    both = (await _mission(client, sid, {"audio_b64": PCM_B64, "text": "typed answer"})).json()
    assert both["transcript"] == "typed answer"
    assert iat.calls == 1  # 文本优先时不再浪费 IAT


@pytest.mark.asyncio
async def test_transcript_anchored_ise_produces_pronunciation_evidence(
    client: AsyncClient,
    scene_root: Path,
    monkeypatch: pytest.MonkeyPatch,
    db: AsyncSession,
) -> None:
    """§5.4: 自由产出的发音证据 = 以**转写为参考文本**的 ISE (transcript_anchored)."""
    monkeypatch.setattr(dg, "_IAT", FakeIAT("A small coffee please."))
    sid = await _ready(client)  # 先开局: 打基础仍走 stub (凭据还没配)
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=88.0))
    body = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert body["sub_scores"]["pronunciation"] == pytest.approx(88.0)
    assert body["word_details"] and body["speech_rate_wpm"]
    pron = next(e for e in body["ability_events"] if e["dimension"] == "pronunciation")
    assert pron["ise_ref_mode"] == "transcript_anchored" and pron["weight"] == 1.0
    fluency = next(e for e in body["ability_events"] if e["dimension"] == "fluency")
    assert fluency["source"] == "xunfei"  # ISE fluency + wpm 综合的口径 (score_read_along)
    step = (
        await db.execute(
            select(PracticeStep).where(PracticeStep.session_id == sid, PracticeStep.step_id == "m1")
        )
    ).scalar_one()
    assert step.ise_ref_mode == "transcript_anchored"
    assert step.score_pronunciation == pytest.approx(88.0)
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.pronunciation == pytest.approx(88.0)


@pytest.mark.asyncio
async def test_anchored_evidence_dropped_when_ise_falls_back_to_stub(
    client: AsyncClient, scene_root: Path, monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    """讯飞配了但调用失败回退 StubASR: 证据整体丢弃 —— 宁可发音空缺, 不造假."""
    monkeypatch.setattr(dg, "_IAT", FakeIAT("A small coffee please."))
    sid = await _ready(client)
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=95.0, source="stub"))
    body = (await _mission(client, sid, {"audio_b64": PCM_B64})).json()
    assert body["sub_scores"]["pronunciation"] is None and body["word_details"] == []
    assert [e for e in body["ability_events"] if e["dimension"] == "pronunciation"] == []
    # 锚定轮自身: m1 一条事件都不产 (无文本输入时语法/词汇也无 LLM 证据可给)
    turn_events = (
        (
            await db.execute(
                select(AbilityEvent).where(
                    AbilityEvent.session_id == sid, AbilityEvent.step_id == "m1"
                )
            )
        )
        .scalars()
        .all()
    )
    assert turn_events == []


# ============================================================ hint


@pytest.mark.asyncio
async def test_hint_marks_next_turn_costs_score_without_judging(
    client: AsyncClient, scene_root: Path, db: AsyncSession
) -> None:
    sid = await _ready(client)
    hint = await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})
    assert hint.status_code == 200, hint.text
    payload = hint.json()
    assert payload["hint"]["task_id"] == "t1" and payload["costs_score"] is True
    assert payload["hint"]["hint_en"] == "A small coffee, please."
    assert payload["hints_used"] == 1

    turn = (await _mission(client, sid, {"text": "hi."})).json()
    assert turn["costs_score"] is True  # 只标记**下一个**判定回合
    follow = (await _mission(client, sid, {"text": "and then?"})).json()
    assert follow["costs_score"] is False  # 一次 hint 只欠一次

    rows = (
        (
            await db.execute(
                select(PracticeStep)
                .where(PracticeStep.session_id == sid)
                .order_by(PracticeStep.step_index)
            )
        )
        .scalars()
        .all()
    )
    mission_rows = [r for r in rows if r.step_type == "mission_turn"]
    assert [r.step_id for r in mission_rows] == ["m1", "m2"]
    assert mission_rows[0].annotated_json["costs_score"] is True
    assert mission_rows[1].annotated_json["costs_score"] is False

    finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    assert finish.json()["report"]["hints_used"] == 1


@pytest.mark.asyncio
async def test_hint_when_all_tasks_done_falls_back_to_script(
    client: AsyncClient, scene_root: Path
) -> None:
    sid = await _ready(client)
    partial = (await _mission(client, sid, {"text": "A small coffee, please."})).json()
    # t1 完成了, 但 t2/t3 还开着 -> 提示仍指向第一个未完成任务
    hint1 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert hint1["hint"]["task_id"] == "t2"
    await _mission(client, sid, {"text": "How much is that?"})
    await _mission(client, sid, {"text": "Thanks, have a good day."})
    assert partial["turn_index"] == 1
    hint2 = (await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})).json()
    assert hint2["hint"]["task_id"] is None
    assert hint2["hint"]["script_line"]  # 全部任务完成: 回落剧本 B 行


@pytest.mark.asyncio
async def test_hint_and_mission_blocked_after_finish(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    await _mission(client, sid, {"text": "hi there."})
    await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={"device_id": DEV})
    hint = await client.post(f"/api/v1/sessions/{sid}/hint", json={"device_id": DEV})
    turn = await _mission(client, sid, {"text": "still talking"})
    assert hint.status_code == 409 and turn.status_code == 409


# ============================================================ 归属 / 身份 / 挂载


@pytest.mark.asyncio
async def test_mission_gate_board_is_distinguishable(client: AsyncClient, scene_root: Path) -> None:
    sid = await _ready(client)
    thief = await client.post(
        f"/api/v1/sessions/{sid}/mission", json={"device_id": "dev-thief", "text": "hello!"}
    )
    missing = await client.post(
        "/api/v1/sessions/no-such-session/mission", json={"device_id": DEV, "text": "x"}
    )
    no_id = await client.post(f"/api/v1/sessions/{sid}/mission", json={"text": "x"})
    no_id_finish = await client.post(f"/api/v1/sessions/{sid}/finish-mission", json={})
    assert thief.status_code == 403 and thief.json()["error"]["code"] == "FORBIDDEN_SESSION"
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "SESSION_NOT_FOUND"
    assert no_id.status_code == 400 and no_id.json()["error"]["code"] == "IDENTITY_REQUIRED"
    assert no_id_finish.status_code == 400
    unknown_user = await client.post(
        f"/api/v1/sessions/{sid}/mission",
        json={"user_id": "00000000-0000-0000-0000-000000000000", "text": "x"},
    )
    assert unknown_user.status_code == 403  # 不认识的账号 = 别人的局 (同 T3 恢复端点)


@pytest.mark.asyncio
async def test_mission_endpoints_mounted_with_review_contract() -> None:
    schema = app.openapi()
    paths = schema["paths"]
    assert {
        "/api/v1/sessions/{session_id}/mission",
        "/api/v1/sessions/{session_id}/hint",
        "/api/v1/sessions/{session_id}/finish-mission",
        "/api/v1/ability",
        "/api/v1/polish",
        "/api/v1/expressions",
    } <= set(paths)
    review = schema["components"]["schemas"]["ReviewReport"]["properties"]
    assert {
        "overall",
        "dims",
        "pronunciation_subs",
        "highlights",
        "improvements",
        "checklist",
        "transcript_pairs",
        "new_tokens",
        "ability_delta",
        "source",
    } <= set(review)
    turn_props = schema["components"]["schemas"]["MissionTurnResponse"]["properties"]
    assert {"newly_done", "checklist", "sub_scores", "polish", "review", "cleared"} <= set(
        turn_props
    )
