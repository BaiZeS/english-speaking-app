"""/dialogue/turn 的 v2.0 扩展测试 (§5.5-4 润色并入单次调用 + §5.6 证据 + 魔法字符串).

旧断言 (``test_dialogue_stub`` / ``test_llm_endpoints`` / ``test_dialogue_iat``)
一条不动也得过 —— 这里只钉**新增**行为:

* 单次 LLM 调用同时回 ``polish`` + 语法/词汇分 (mock 返回扩展 JSON);
  模型只回 ``{reply, suggestion}`` (旧 prompt 形状) 时新字段为 null 但不报错;
* 带身份的轮次把证据写进 §5.6 管线: 未配置讯飞 -> 没有发音证据; 配了真 ISE ->
  ``transcript_anchored`` 一条不少; **客户端自选模型出的分不进画像** (判分口径
  恒为服务端默认模型), 润色对照另记 ``annotated_diffs``;
* 不带身份的轮次 = 纯旧行为 (零落库, 但 UI 字段照给);
* history 回填按**结构** (末尾 user 回合) 而不是魔法字面量: 新客户端空串标记
  与旧客户端占位文本都会被替换; 用户真打过字的末尾回合不动。
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import dialogue
from app.api.v1.dialogue import _apply_recognized_text
from app.config import settings
from app.models.db import AbilityEvent, AbilityProfile, AnnotatedDiff, User
from app.services import llm_provider
from app.services import mission_engine as me
from tests.test_drill_grader import FakeASR, install_llm

DEV = "dev-dialogue-polish"


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


def turn_payload(**over: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "scene_id": "daily_conversation",
        "history": [
            {"role": "assistant", "text": "How was your weekend?"},
            {"role": "user", "text": "I go to park yesterday."},
        ],
    }
    payload.update(over)
    return payload


def rich_reply(
    grammar: float | None = 61.0, vocabulary: float | None = 66.0, polished: str | None = None
) -> str:
    polish = None
    if polished is not None:
        polish = {
            "original": "I go to park yesterday.",
            "polished": polished,
            "explanation_cn": "昨天发生过的事要用过去时 went。",
        }
    return json.dumps(
        {
            "reply": "A park? That sounds relaxing!",
            "suggestion": "I went to the park with my family.",
            "polish": polish,
            "grammar_score": grammar,
            "vocabulary_score": vocabulary,
        },
        ensure_ascii=False,
    )


# ============================================================ 响应扩展 (add-only)


@pytest.mark.asyncio
async def test_turn_adds_polish_and_scores_in_one_call(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = install_llm(
        monkeypatch,
        [rich_reply(polished="I went to the park yesterday.")],
    )
    res = await client.post("/api/v1/dialogue/turn", json=turn_payload())
    body = res.json()
    assert len(fake.requests) == 1  # 一次调用拿到全部 (§5.5-4)
    assert res.status_code == 200 and body["status"] == "ready"
    assert body["reply_text"] == "A park? That sounds relaxing!"
    assert body["suggested_reply"].startswith("I went")
    assert body["polish"]["polished"] == "I went to the park yesterday."
    assert body["polish"]["original"] == "I go to park yesterday."
    assert body["grammar_score"] == 61.0 and body["vocabulary_score"] == 66.0
    assert body["llm_source"] == "qwen3.8-max"
    # 未带身份 = 不落库 (旧客户端零副作用)
    assert body["ability_events"] == []


@pytest.mark.asyncio
async def test_turn_legacy_shaped_reply_still_ready_with_null_extras(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """旧形状 JSON ({reply, suggestion}) 不报错: 新字段 null, status 仍 ready."""
    install_llm(monkeypatch, [json.dumps({"reply": "Cool!", "suggestion": "Nice day."})])
    body = (await client.post("/api/v1/dialogue/turn", json=turn_payload())).json()
    assert body["status"] == "ready" and body["reply_text"] == "Cool!"
    assert body["polish"] is None and body["grammar_score"] is None
    assert body["llm_source"] == "qwen3.8-max"


@pytest.mark.asyncio
async def test_out_of_range_scores_are_dropped_not_clamped(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, [rich_reply(grammar=250.0, vocabulary=None)])
    body = (await client.post("/api/v1/dialogue/turn", json=turn_payload())).json()
    assert body["grammar_score"] is None  # 越界分不进画像也不当真, 直接视为无证据
    assert body["vocabulary_score"] is None


# ============================================================ 画像写侧


@pytest.mark.asyncio
async def test_turn_with_identity_persists_grammar_vocabulary_events(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(device_id=DEV)
    db.add(user)
    await db.commit()
    install_llm(monkeypatch, [rich_reply(polished="I went to the park yesterday.")])
    body = (await client.post("/api/v1/dialogue/turn", json=turn_payload(device_id=DEV))).json()
    assert {e["dimension"] for e in body["ability_events"]} == {"grammar", "vocabulary"}
    rows = (await db.execute(select(AbilityEvent))).scalars().all()
    assert {(r.dimension, r.source_kind, r.weight) for r in rows} == {
        ("grammar", "llm", 1.0),
        ("vocabulary", "llm", 1.0),
    }
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.grammar == pytest.approx(61.0) and profile.vocabulary == pytest.approx(66.0)
    assert profile.cefr_level is None
    diffs = (await db.execute(select(AnnotatedDiff))).scalars().all()
    assert [(d.origin, d.polished) for d in diffs] == [
        ("dialogue", "I went to the park yesterday.")
    ]


@pytest.mark.asyncio
async def test_turn_without_identity_writes_nothing(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, [rich_reply(polished="I went to the park yesterday.")])
    await client.post("/api/v1/dialogue/turn", json=turn_payload())
    assert (await db.execute(select(AbilityEvent))).scalars().all() == []
    assert (await db.execute(select(AnnotatedDiff))).scalars().all() == []


@pytest.mark.asyncio
async def test_client_chosen_model_scores_stay_out_of_the_profile(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """客户端自选模型只影响人设文本; 画像判分口径恒为服务端默认 (T3 先例)."""
    user = User(device_id=DEV)
    db.add(user)
    await db.commit()
    install_llm(monkeypatch, [rich_reply()])  # default = qwen3.8-max (install_llm 设的)
    body = (
        await client.post(
            "/api/v1/dialogue/turn", json=turn_payload(model_id="qwen-turbo", device_id=DEV)
        )
    ).json()
    assert body["model_id"] == "qwen-turbo"  # 文本照旧跟随客户端
    assert body["grammar_score"] == 61.0  # 分也回给 UI
    assert body["ability_events"] == []  # 但不进画像
    assert (await db.execute(select(AbilityEvent))).scalars().all() == []
    assert (await db.execute(select(AbilityProfile))).scalars().all() == []


@pytest.mark.asyncio
async def test_unknown_user_id_on_turn_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, [rich_reply()])
    res = await client.post(
        "/api/v1/dialogue/turn",
        json=turn_payload(user_id="00000000-0000-0000-0000-000000000000"),
    )
    assert res.status_code == 404 and res.json()["error"]["code"] == "USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_anchored_ise_feeds_pronunciation_for_free_dialogue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """讯飞配齐 + 有音频有转写 -> 发音证据 (transcript_anchored) 进事件列表."""
    audio = b"\x00\x01" * 3200

    async def fake_transcribe(_pcm: bytes) -> str | None:
        return "I went to the park."

    class _Iat:
        transcribe = staticmethod(fake_transcribe)

    monkeypatch.setattr(dialogue, "_iat", _Iat())
    sid_probe = await dialogue.turn(
        dialogue.DialogueTurnRequest(
            scene_id="daily_conversation",
            history=[],
            user_audio_b64=base64.b64encode(audio).decode(),
        )
    )
    assert sid_probe.recognized_text == "I went to the park."
    # 没配凭据: 不产发音证据 (回声 95 不算数)
    assert [e for e in sid_probe.ability_events if e.dimension == "pronunciation"] == []

    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=82.0))
    anchored = await me.anchored_pronunciation(audio, "I went to the park.")
    assert anchored is not None and anchored.pronunciation == pytest.approx(82.0)
    events = me.turn_ability_events(
        me.MissionTurnJudgement(reply="r", grammar_score=None, vocabulary_score=None),
        anchored,
        score_source="heuristic",
    )
    dims = {(e.dimension, e.weight, e.ise_ref_mode) for e in events}
    assert ("pronunciation", 1.0, "transcript_anchored") in dims
    assert ("fluency", 1.0, None) in dims


# ============================================================ 魔法字符串退役


def test_trailing_user_turn_replaced_by_structure_not_literal() -> None:
    # v2.0 新协议: 末尾 user 回合留空 = "这句待回填" —— 不依赖任何占位文本
    history = [
        {"role": "assistant", "text": "Hi!"},
        {"role": "user", "text": ""},
    ]
    updated = _apply_recognized_text(history, "I like tea.")
    assert updated[-1]["text"] == "I like tea."
    # 旧客户端占位文本仍兼容 (§四 add-only), 但只是并列的可替换标记之一
    legacy = [{"role": "user", "text": dialogue._PLACEHOLDER_USER_TEXT}]
    assert _apply_recognized_text(legacy, "Sure, thanks.")[-1]["text"] == "Sure, thanks."
    # 末尾 user 回合已有真实文本 (手输) -> 不动它, 也不越过它去找更早的占位
    typed = [
        {"role": "user", "text": dialogue._PLACEHOLDER_USER_TEXT},
        {"role": "assistant", "text": "echo"},
        {"role": "user", "text": "typed by hand"},
    ]
    assert _apply_recognized_text(typed, "noise") == typed
    # 没有转写 -> 原对象返回 (旧断言钉过的 identity)
    same: list[dict[str, str]] = [{"role": "user", "text": dialogue._PLACEHOLDER_USER_TEXT}]
    assert _apply_recognized_text(same, None) is same
