"""v3.0 群聊一轮 (T4) 与每轮评分作业 (T5).

钉住的是四条会被"顺手优化掉"的行为契约:

1. **听不出来说话就整轮不前进** —— 语音模式转写为空时 422, 会话里一个气泡都不多。
   让教练去"回应一句不知道是什么的话"等于替学员编造了他说过什么。
2. **拿不到台词 503 且不落库** (v2.3.0 的 D5) —— 不回放目录句、不写兜底气泡。
3. **语音条是快路, 不是门槛** —— 合成超时/失败只让 ``audio_pending=true``, 仍 200。
   台词都已经生成好了, 因为没声音而失败是最坏的错误分类。
4. **评分在请求之外** —— 请求把评分卡以 ``pending`` 落一颗, 作业把它翻成 ``ready``;
   作业失败**静默** (``failed`` = 没有点评, 不是这一轮不存在), 且过水位能翻身。

发音分只在"语音 + 转写里没有汉字"时才有: 说中文或打字的那一轮**不写这一轴**
(不写 0 分 —— 0 分是说"测了且很差", 而这里根本没测)。
"""

from __future__ import annotations

import asyncio
import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import dialogue_threads as dt
from app.config import settings
from app.models.db import DialogueThread
from app.services import thread_audio, thread_grading, thread_store
from app.services.mission_engine import AnchoredPronunciation
from app.services.users import lookup_user
from tests.test_dialogue_threads import DEV_A as DEV
from tests.test_dialogue_threads import SCENE, _open, _q
from tests.test_drill_grader import install_llm


def group_generation(
    *,
    reply: str = "So which dish are you going to try?",
    reply_cn: str = "那你准备点哪道菜?",
    suggestion: str = "I'll have the beef noodles, please.",
    suggestion_cn: str = "我要一份牛肉面。",
    learner_cn: str = "我想吃面。",
    speaker: str = "r1",
    next_beat: str = "",
) -> str:
    """群聊台词的七字段 JSON (五字段 + speaker + next_beat)."""
    return json.dumps(
        {
            "reply": reply,
            "reply_cn": reply_cn,
            "suggestion": suggestion,
            "suggestion_cn": suggestion_cn,
            "learner_cn": learner_cn,
            "speaker": speaker,
            "next_beat": next_beat,
        }
    )


def grade_json(
    *,
    relevance: int = 88,
    informativeness: int = 72,
    appropriateness: int = 90,
    beat_progress: bool = True,
    comment: str = "Good - you named the dish and the ask.",
    comment_cn: str = "很好, 你说清了要什么。",
) -> str:
    return json.dumps(
        {
            "relevance": relevance,
            "informativeness": informativeness,
            "appropriateness": appropriateness,
            "beat_progress": beat_progress,
            "comment": comment,
            "comment_cn": comment_cn,
        }
    )


class _FakeIat:
    """听写替身: 记下每次被要求的语言, 返回固定文本 (或 None = 没听清)."""

    def __init__(self, result: str | None) -> None:
        self.result = result
        self.calls: list[str] = []

    async def transcribe(self, pcm: bytes, *, language: str = "en_us") -> str | None:
        self.calls.append(language)
        return self.result


class _TtsOk:
    def __init__(self, text: str, voice: str) -> None:
        self.duration_ms = 1200
        self.audio_url = f"/static/tts/fake-{abs(hash((text, voice))) % 1000:03d}.wav"
        self.source = "mimo"


class _FakeTts:
    def __init__(self, *, fail: bool = False, slow: bool = False) -> None:
        self.fail = fail
        self.slow = slow
        self.calls: list[tuple[str, str]] = []

    async def synthesize(self, text: str, voice: str) -> Any:
        self.calls.append((text, voice))
        if self.fail:
            raise RuntimeError("tts down")
        if self.slow:
            await asyncio.sleep(thread_audio.TTS_TURN_BUDGET_S + 0.5)
        return _TtsOk(text, voice)


@pytest.fixture(autouse=True)
def _no_background_grading(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """端点会真的派生判分作业 —— 它和用例自己的直接调用抢同一颗评分卡。

    仓内约定 (同 ``spawn_scene_brief_job`` 的处理): 测试里把派生变成 no-op 并记录调用,
    要跑作业的用例自己 ``await run_thread_grading_job(...)``。
    """
    spawned: list[str] = []
    monkeypatch.setattr(
        dt.thread_grading, "spawn_thread_grading", lambda tid, uid: spawned.append(tid)
    )
    return spawned


async def _thread_id(client: AsyncClient) -> str:
    return (await _open(client, DEV)).json()["id"]


async def _post_turn(client: AsyncClient, thread_id: str, payload: dict[str, Any]):
    return await client.post(
        f"/api/v1/dialogue/threads/{thread_id}/turn", json=payload, params=_q(DEV)
    )


async def _text_turn(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
    *,
    text: str = "I want noodles",
    generation: str | None = None,
) -> dict[str, Any]:
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts())
    install_llm(monkeypatch, generation=[generation or group_generation()])
    resp = await _post_turn(client, await _thread_id(client), {"mode": "text", "text": text})
    assert resp.status_code == 200, resp.text
    return resp.json()


# ====== T4: 输入分派 ======


@pytest.mark.asyncio
async def test_text_turn_writes_four_bubbles_and_skips_iat(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake_iat = _FakeIat("不该被调用")
    monkeypatch.setattr(dt, "_iat", fake_iat)
    body = await _text_turn(client, monkeypatch)

    kinds = [m["kind"] for m in body["messages"]]
    assert kinds == [
        thread_store.KIND_USER,
        thread_store.KIND_LINE,
        thread_store.KIND_HINT,
        thread_store.KIND_GRADE,
    ], kinds
    assert fake_iat.calls == [], "打字这一轮不该去听写"
    assert body["grading_status"] == thread_store.GRADING_PENDING


@pytest.mark.asyncio
async def test_voice_turn_uses_zh_cn_and_does_not_run_ise_for_chinese(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """中文回答: 听写走 zh_cn, **不跑**英文逐词 ISE, 也不产出发音轴."""
    thread_id = await _thread_id(client)
    fake_iat = _FakeIat("我想要一碗牛肉面")
    monkeypatch.setattr(dt, "_iat", fake_iat)
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts())
    install_llm(monkeypatch, generation=[group_generation()])

    ise_calls: list[str] = []

    async def _no_ise(audio: bytes, transcript: str, **kw: Any) -> None:
        ise_calls.append(transcript)
        return None

    monkeypatch.setattr("app.services.mission_engine.anchored_pronunciation", _no_ise)

    resp = await _post_turn(
        client,
        thread_id,
        {"mode": "voice", "audio_b64": base64.b64encode(b"\x00" * 3200).decode()},
    )
    assert resp.status_code == 200, resp.text
    assert fake_iat.calls == ["zh_cn"], "语音必须走中英混读那一条听写路"
    assert ise_calls == [], "说中文不该跑英文发音评测"

    turn = resp.json()
    user = next(m for m in turn["messages"] if m["kind"] == thread_store.KIND_USER)
    assert user["spoke"] == "zh"
    assert user["recognized_text"] == "我想要一碗牛肉面"
    grade = next(m for m in turn["messages"] if m["kind"] == thread_store.KIND_GRADE)
    assert "pronunciation" not in grade["grade"]["axes"], grade["grade"]


@pytest.mark.asyncio
async def test_voice_turn_in_english_runs_ise_and_records_pronunciation(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread_id = await _thread_id(client)
    monkeypatch.setattr(dt, "_iat", _FakeIat("I want the beef noodles"))
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts())
    install_llm(monkeypatch, generation=[group_generation()])

    seen: list[str] = []

    async def _fake_ise(audio: bytes, transcript: str, **kw: Any) -> AnchoredPronunciation:
        seen.append(transcript)
        return AnchoredPronunciation(
            pronunciation=81.0,
            fluency=77.0,
            completeness=90.0,
            speech_rate_wpm=120.0,
            word_details=[],
        )

    monkeypatch.setattr("app.services.mission_engine.anchored_pronunciation", _fake_ise)

    resp = await _post_turn(
        client,
        thread_id,
        {"mode": "voice", "audio_b64": base64.b64encode(b"\x00" * 3200).decode()},
    )
    assert resp.status_code == 200, resp.text
    turn = resp.json()
    assert seen == ["I want the beef noodles"], "发音分的参考文本必须是转写本身"
    user = next(m for m in turn["messages"] if m["kind"] == thread_store.KIND_USER)
    assert user["spoke"] == "en"
    grade = next(m for m in turn["messages"] if m["kind"] == thread_store.KIND_GRADE)
    assert grade["grade"]["axes"]["pronunciation"] == 81.0, grade["grade"]


@pytest.mark.asyncio
async def test_voice_turn_with_empty_transcription_is_422_and_adds_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """没配讯飞/超时/真的没听清 -> 422 且**会话完全不动** (不替学员编一句话)."""
    thread_id = await _thread_id(client)
    before = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    monkeypatch.setattr(dt, "_iat", _FakeIat(None))
    install_llm(monkeypatch, generation=[group_generation()])

    resp = await _post_turn(
        client,
        thread_id,
        {"mode": "voice", "audio_b64": base64.b64encode(b"\x00" * 3200).decode()},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "VOICE_TRANSCRIPTION_FAILED"

    after = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    assert len(after["messages"]) == len(before["messages"]), "失败的一轮不许留下气泡"


@pytest.mark.asyncio
async def test_voice_without_audio_and_text_without_text_are_422(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    thread_id = await _thread_id(client)
    install_llm(monkeypatch, generation=[group_generation()])

    no_audio = await _post_turn(client, thread_id, {"mode": "voice"})
    assert no_audio.status_code == 422
    no_text = await _post_turn(client, thread_id, {"mode": "text", "text": "  "})
    assert no_text.status_code == 422


@pytest.mark.asyncio
async def test_bad_base64_audio_is_422_not_500(client: AsyncClient) -> None:
    thread_id = await _thread_id(client)
    resp = await _post_turn(client, thread_id, {"mode": "voice", "audio_b64": "!!!not base64!!!"})
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "BAD_AUDIO"


# ====== T4: 台词与语音条 ======


@pytest.mark.asyncio
async def test_llm_unavailable_is_503_and_turn_is_not_persisted(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D5: 拿不到台词 -> 503, 这一轮**什么都没发生** (不回放目录句、不写兜底气泡)."""
    thread_id = await _thread_id(client)
    before = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts())
    # 仓内口径: 未配凭据 = 拿不到台词 (不是"降级成目录句")。
    monkeypatch.setattr(settings, "llm_api_key", "")

    resp = await _post_turn(client, thread_id, {"mode": "text", "text": "I want noodles"})
    assert resp.status_code == 503, resp.text
    assert resp.json()["error"]["code"] == "TURN_GENERATION_UNAVAILABLE"

    after = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    assert len(after["messages"]) == len(before["messages"])
    assert after["turn_count"] == before["turn_count"], "失败的一轮不许推进 turn_count"


@pytest.mark.asyncio
async def test_tts_over_budget_is_still_200_with_pending_audio(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """语音条是快路: 合成超时只让 ``audio_pending=true``, 绝不能拖垮已经成功的台词."""
    thread_id = await _thread_id(client)
    monkeypatch.setattr(dt, "_iat", _FakeIat("我想点面"))
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts(slow=True))
    install_llm(monkeypatch, generation=[group_generation()])

    resp = await _post_turn(
        client,
        thread_id,
        {"mode": "voice", "audio_b64": base64.b64encode(b"\x00" * 3200).decode()},
    )
    assert resp.status_code == 200, resp.text
    line = next(m for m in resp.json()["messages"] if m["kind"] == thread_store.KIND_LINE)
    assert line["audio_url"] is None and line["audio_pending"] is True, line


@pytest.mark.asyncio
async def test_tts_failure_is_soft(client: AsyncClient, monkeypatch: pytest.MonkeyPatch) -> None:
    thread_id = await _thread_id(client)
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts(fail=True))
    install_llm(monkeypatch, generation=[group_generation()])

    resp = await _post_turn(client, thread_id, {"mode": "text", "text": "I want noodles"})
    assert resp.status_code == 200
    line = next(m for m in resp.json()["messages"] if m["kind"] == thread_store.KIND_LINE)
    assert line["audio_pending"] is True


@pytest.mark.asyncio
async def test_unknown_speaker_falls_back_to_first_role(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """模型拼错 speaker 时台词仍要有人认领 —— 挂到本场第一个角色, 不画空气泡."""
    thread_id = await _thread_id(client)
    monkeypatch.setattr(thread_audio, "_provider", _FakeTts())
    install_llm(monkeypatch, generation=[group_generation(speaker="r99")])

    resp = await _post_turn(client, thread_id, {"mode": "text", "text": "I want noodles"})
    assert resp.status_code == 200
    line = next(m for m in resp.json()["messages"] if m["kind"] == thread_store.KIND_LINE)
    assert line["role_id"] == "r1", line


@pytest.mark.asyncio
async def test_reply_audio_url_is_absolute(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = await _text_turn(client, monkeypatch)
    line = next(m for m in body["messages"] if m["kind"] == thread_store.KIND_LINE)
    assert line["audio_url"].startswith("http"), line["audio_url"]
    assert line["audio_ms"] == 1200


# ====== T4: 议程游标 ======


def test_beat_cursor_only_advances_and_cannot_outrun_the_agenda() -> None:
    from app.services import dialogue_scenes

    scene = dialogue_scenes.resolve_scene(SCENE)
    assert scene is not None
    cases = [
        ("", 2, 2),
        ("3", 2, 3),
        ("1", 3, 3),  # 回退: 忽略
        (str(len(scene.beats) + 5), 2, 2),  # 越界: 忽略
        ("abc", 2, 2),
    ]
    for next_beat, start, expected in cases:
        got = dt.thread_turn.beat_cursor_after(start, scene, next_beat)
        assert got == expected, f"next_beat={next_beat!r} from {start}"


# ====== T5: 判分作业 ======


async def _last_grade(db: AsyncSession, thread_id: str, user_id: str) -> dict[str, Any]:
    row = await thread_store.get_thread(db, thread_id, user_id)
    assert row is not None
    grades = [m for m in thread_store.messages_of(row.doc) if m["kind"] == thread_store.KIND_GRADE]
    assert grades, row.doc
    return grades[-1]


async def _dev_user_id(db: AsyncSession) -> str:
    user = await lookup_user(db, device_id=DEV)
    assert user is not None
    return user.id


@pytest.mark.asyncio
async def test_grading_job_flips_pending_to_ready(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = await _text_turn(client, monkeypatch)
    thread_id = body["thread_id"]
    user_id = await _dev_user_id(db)
    install_llm(monkeypatch, thread_grading=[grade_json()])

    await thread_grading.run_thread_grading_job(thread_id, user_id)

    payload = (await _last_grade(db, thread_id, user_id))["grade"]
    assert payload["status"] == thread_store.GRADING_READY, payload
    # (88+72+90)/3 = 83.3, 推进议程 +5 -> 88.3, 取整 88
    assert payload["score"] == 88, payload
    assert set(payload["axes"]) == {
        "relevance",
        "informativeness",
        "appropriateness",
        "beat_progress",
    }, payload
    assert payload["comment_cn"], payload

    echoed = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    assert echoed["grading_status"] == thread_store.GRADING_READY


@pytest.mark.asyncio
async def test_grading_job_failure_is_silent_and_terminal(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """判不出来 = 没有点评, **不是**这一轮不存在: 气泡还在, 状态落 failed."""
    body = await _text_turn(client, monkeypatch)
    thread_id = body["thread_id"]
    user_id = await _dev_user_id(db)

    async def _unavailable(*a: Any, **kw: Any) -> None:
        raise thread_grading.LlmUnavailableError("judge down")

    monkeypatch.setattr(thread_grading, "_judge", _unavailable)
    await thread_grading.run_thread_grading_job(thread_id, user_id)

    assert (await _last_grade(db, thread_id, user_id))["grade"]["status"] == (
        thread_store.GRADING_FAILED
    )
    echoed = (await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))).json()
    kinds = [m["kind"] for m in echoed["messages"]]
    assert thread_store.KIND_GRADE in kinds, "failed 不许把评分卡连同这一轮抹掉"


@pytest.mark.asyncio
async def test_grading_job_is_idempotent_after_terminal_state(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重跑作业不许把同一颗评分卡判第二次 (分数会漂, 而"判过"这件事只该有一次)."""
    body = await _text_turn(client, monkeypatch)
    thread_id = body["thread_id"]
    user_id = await _dev_user_id(db)

    install_llm(
        monkeypatch,
        thread_grading=[grade_json(relevance=90, informativeness=90, appropriateness=90)],
    )
    await thread_grading.run_thread_grading_job(thread_id, user_id)
    first = await _last_grade(db, thread_id, user_id)

    install_llm(
        monkeypatch,
        thread_grading=[grade_json(relevance=10, informativeness=10, appropriateness=10)],
    )
    await thread_grading.run_thread_grading_job(thread_id, user_id)
    second = await _last_grade(db, thread_id, user_id)

    assert second["grade"]["score"] == first["grade"]["score"], "终态被重判了"


async def _age_the_pending_grade(db: AsyncSession, thread_id: str, seconds: float) -> None:
    """把那颗 pending 评分卡的 ``at`` 拨老 —— 水位读的是它, 不是 ``updated_at``."""
    row = await thread_store.get_thread(db, thread_id, await _dev_user_id(db))
    assert row is not None
    doc = thread_store.load_doc(row)
    aged = False
    for message in thread_store.messages_of(doc):
        grade = message.get("grade")
        if isinstance(grade, dict) and grade.get("status") == thread_store.GRADING_PENDING:
            message["at"] = (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat(
                timespec="seconds"
            )
            aged = True
    assert aged, "没有 pending 的评分卡可拨"
    assert await thread_store.save_doc(db, row, doc)


@pytest.mark.asyncio
async def test_watermark_redispatch_happens_when_no_job_is_in_flight(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _no_background_grading: list[str],
) -> None:
    """进程重启后那颗 pending 只能靠 GET 的水位翻身 —— 否则永远停在「评分生成中…」."""
    thread_id = (await _text_turn(client, monkeypatch))["thread_id"]
    await _age_the_pending_grade(db, thread_id, thread_grading.REDISPATCH_AFTER_S + 1)

    _no_background_grading.clear()
    await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))
    assert _no_background_grading == [thread_id], _no_background_grading


@pytest.mark.asyncio
async def test_marking_read_does_not_reset_the_watermark(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _no_background_grading: list[str],
) -> None:
    """回归锁: 标已读会写这一行, 但不许把水位时钟拨回零点.

    最早那版用 ``row.updated_at`` 计时 —— 于是"每打开一次聊天就续一次命", 挂死的
    评分卡永远够不到水位, 进程重启后再没人来翻它。
    """
    thread_id = (await _text_turn(client, monkeypatch))["thread_id"]
    await _age_the_pending_grade(db, thread_id, thread_grading.REDISPATCH_AFTER_S + 1)

    _no_background_grading.clear()
    await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))  # 这次标已读
    assert _no_background_grading == [thread_id], "标已读把水位清掉了"


@pytest.mark.asyncio
async def test_no_redispatch_while_a_job_is_running_or_when_ready(
    client: AsyncClient,
    db: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
    _no_background_grading: list[str],
) -> None:
    thread_id = (await _text_turn(client, monkeypatch))["thread_id"]
    await _age_the_pending_grade(db, thread_id, thread_grading.REDISPATCH_AFTER_S + 1)

    monkeypatch.setattr(thread_grading, "_IN_FLIGHT", {thread_id})
    _no_background_grading.clear()
    await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))
    assert _no_background_grading == [], "作业还在跑就不该再派一个"

    monkeypatch.setattr(thread_grading, "_IN_FLIGHT", set())
    row = await db.get(DialogueThread, thread_id)
    assert row is not None
    row.grading_status = thread_store.GRADING_READY
    await db.commit()
    _no_background_grading.clear()
    await client.get(f"/api/v1/dialogue/threads/{thread_id}", params=_q(DEV))
    assert _no_background_grading == [], "已经 ready 还重派就是白烧一次 LLM"
