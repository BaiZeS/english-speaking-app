"""/dialogue/turn 的判分面 (§A4: 判分搬出这条请求; §5.6 证据 + D2 门控).

历史: 这条路由曾用**一次**调用同时拿台词 + 润色 + 语法/词汇分 (§5.5-4 的"并入单次调用")。
§A(D1) 拆调用之后它只剩台词那一半 (:class:`TurnGeneration` 五字段), 判分**不在请求里**:
学员要润色走现成的 ``POST /polish`` (纯文本工具, 不进画像)。于是本文件钉四件事:

* 响应形状: 判分字段诚实缺席 (``polish``/分数 null), 而不是塞一份没人判的分;
* 身份管道真的接通: 带 ``device_id`` 才落库, 不带就零副作用 (旧客户端行为不变);
* **D2 门控仍然成立**: 客户端自选模型出的分不进画像 —— 今天没有生产者会往自由对话传分,
  所以这条直接调 :func:`dialogue._persist_turn_evidence` 断 (规矩不该因为没人用就消失);
* history 回填按**结构** (末尾 user 回合) 而不是魔法字面量。
"""

from __future__ import annotations

import base64
from collections.abc import Iterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1 import dialogue
from app.api.v1.dialogue import _apply_recognized_text
from app.config import settings
from app.models.db import AbilityEvent, AbilityProfile, AnnotatedDiff, User
from app.services import dialogue_scenes, llm_provider
from app.services import mission_engine as me
from tests.test_drill_grader import FakeASR, install_llm
from tests.test_mission import generation_json

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


# ============================================================ 响应形状 (add-only)


@pytest.mark.asyncio
async def test_turn_response_carries_no_grading_any_more(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """§A4: 一次调用只出台词 + 双语; 判分字段保留但**诚实缺席** (值由 /polish 或后续补)。

    旧断言 ("一次调用拿到 polish + 两个分") 是 §5.5-4 的口径, 已被实测推翻 (D1): 台词的墙
    14s 装不下判分, 硬塞就是生产那 7/8 轮降级。这条用例现在钉的是**反面** —— 那几个字段
    不许再有人偷偷填上。
    """
    fake = install_llm(monkeypatch, generation=[generation_json()])
    res = await client.post("/api/v1/dialogue/turn", json=turn_payload())
    body = res.json()
    assert len(fake.requests) == 1  # 请求里**只有**这一次调用
    assert res.status_code == 200 and body["status"] == "ready"
    assert body["reply_text"] and body["suggested_reply"]
    assert body["polish"] is None
    assert body["grammar_score"] is None and body["vocabulary_score"] is None
    assert body["llm_source"] == "qwen3.8-max"


@pytest.mark.asyncio
async def test_turn_without_identity_writes_nothing(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, generation=[generation_json()])
    await client.post("/api/v1/dialogue/turn", json=turn_payload())
    assert (await db.execute(select(AbilityEvent))).scalars().all() == []
    assert (await db.execute(select(AnnotatedDiff))).scalars().all() == []


@pytest.mark.asyncio
async def test_unknown_user_id_on_turn_is_404(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_llm(monkeypatch, generation=[generation_json()])
    res = await client.post(
        "/api/v1/dialogue/turn",
        json=turn_payload(user_id="00000000-0000-0000-0000-000000000000"),
    )
    assert res.status_code == 404 and res.json()["error"]["code"] == "USER_NOT_FOUND"


# ============================================================ 画像写侧 (D2 门控)


@pytest.mark.asyncio
async def test_client_chosen_model_scores_stay_out_of_the_profile(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """客户端自选模型≠服务端默认时**不污染**画像 (T3 先例 / D2).

    §A4 之后这条路由不再产分, 所以门控由调用点转为**单元**钉法: 规矩就是规矩 ——
    谁将来把分数接回自由对话, 都必须走这道门。
    """
    user = User(device_id=DEV)
    db.add(user)
    await db.commit()
    install_llm(monkeypatch, generation=[generation_json()])  # default = qwen3.8-max
    events = await dialogue._persist_turn_evidence(
        db,
        user=user,
        scene_id="daily_conversation",
        anchored=None,
        model="qwen-turbo",  # 客户端选的, 不是服务端默认
        grammar=61.0,
        vocabulary=66.0,
    )
    assert events == []
    assert (await db.execute(select(AbilityEvent))).scalars().all() == []
    assert (await db.execute(select(AbilityProfile))).scalars().all() == []


@pytest.mark.asyncio
async def test_server_default_model_scores_enter_the_profile(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """同一道门的**正面**: 走的确实是服务端默认模型时分才进画像 (D2 的另一半)."""
    user = User(device_id=DEV + "-2")
    db.add(user)
    await db.commit()
    install_llm(monkeypatch, generation=[generation_json()])
    events = await dialogue._persist_turn_evidence(
        db,
        user=user,
        scene_id="daily_conversation",
        anchored=None,
        model="qwen3.8-max",
        grammar=61.0,
        vocabulary=66.0,
    )
    assert {event.dimension for event in events} == {"grammar", "vocabulary"}
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.grammar == pytest.approx(61.0) and profile.vocabulary == pytest.approx(66.0)


@pytest.mark.asyncio
async def test_turn_with_identity_and_ise_writes_anchored_evidence(
    client: AsyncClient, db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """身份 + 音频 + 讯飞配齐 -> 发音/流利两条 ``transcript_anchored`` 证据落库.

    这是"自由对话从没往画像写过一笔"那件事的正面验收 (§4 第 5 条): ``device_id`` 一路
    传到 :func:`dialogue._persist_turn_evidence`, 画像真的动了。
    """
    user = User(device_id=DEV + "-3")
    db.add(user)
    await db.commit()
    install_llm(monkeypatch, generation=[generation_json()])

    async def fake_transcribe(_pcm: bytes) -> str:
        return "I went to the park."

    class _Iat:
        transcribe = staticmethod(fake_transcribe)

    monkeypatch.setattr(dialogue, "_iat", _Iat())
    for field in ("xunfei_app_id", "xunfei_api_key", "xunfei_api_secret"):
        monkeypatch.setattr(settings, field, "test")
    monkeypatch.setattr(me, "_ISE", FakeASR(scores=82.0))

    body = (
        await client.post(
            "/api/v1/dialogue/turn",
            json=turn_payload(
                device_id=DEV + "-3",
                history=[],
                user_audio_b64=base64.b64encode(b"\x00\x01" * 3200).decode(),
            ),
        )
    ).json()
    assert body["recognized_text"] == "I went to the park."
    dims = {event["dimension"] for event in body["ability_events"]}
    assert dims == {"pronunciation", "fluency"}
    rows = (await db.execute(select(AbilityEvent))).scalars().all()
    assert {(row.dimension, row.source_kind, row.weight) for row in rows} == {
        ("pronunciation", "xunfei", 1.0),
        ("fluency", "xunfei", 1.0),
    }
    profile = (await db.execute(select(AbilityProfile))).scalar_one()
    assert profile.pronunciation == pytest.approx(82.0)


@pytest.mark.asyncio
async def test_anchored_ise_dropped_without_credentials(
    monkeypatch: pytest.MonkeyPatch, db: AsyncSession
) -> None:
    """没配讯飞凭据: **不产**发音证据 (回声 95 不算数, §5.6 宁缺勿滥)."""
    audio = b"\x00\x01" * 3200

    async def fake_transcribe(_pcm: bytes) -> str:
        return "I went to the park."

    class _Iat:
        transcribe = staticmethod(fake_transcribe)

    monkeypatch.setattr(dialogue, "_iat", _Iat())
    install_llm(monkeypatch, generation=[generation_json()])
    user = User(device_id=DEV + "-4")
    db.add(user)
    await db.commit()
    probe = await dialogue.turn(
        dialogue.DialogueTurnRequest(
            scene_id="daily_conversation",
            history=[],
            user_audio_b64=base64.b64encode(audio).decode(),
            device_id=DEV + "-4",
        ),
        db=db,
    )
    assert probe.recognized_text == "I went to the park."
    assert probe.ability_events == []
    # helper 本身的口径: 没凭据 -> None (不喂 StubASR 的假分)
    assert await me.anchored_pronunciation(audio, "I went to the park.") is None


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


def test_shown_suggestions_are_capped_and_trimmed() -> None:
    """§A4 add-only 字段的边界: ≤8 条、去空、单条截断 (别让它变成无界 prompt 注入面)."""
    raw: list[Any] = [f"Sentence {index}." for index in range(12)]
    raw[0] = "   "
    kept = dialogue._shown_suggestions(raw)
    assert len(kept) == 7  # 8 条上限里有一条是空的
    assert kept[0] == "Sentence 1."
    # 上限是**共用**的那一份 (实战侧的 `_recent_lines_block` 用同一个数)
    assert dialogue._LINE_MAX_CHARS is me.LINE_MAX_CHARS
    assert dialogue._shown_suggestions([""]) == []
    assert len(dialogue._shown_suggestions(["x" * 500])[0]) <= me.LINE_MAX_CHARS


def test_repeat_block_lists_coach_lines_and_shown_suggestions() -> None:
    """§A5: 反重复清单 = 历史里的 Coach 台词 + 客户端 echo 的已给参考句."""
    history: list[dict[str, Any]] = [
        {"role": "user", "text": "Hi"},
        {"role": "assistant", "text": "How was your weekend?"},
    ]
    block = dialogue._repeat_block(history, ["I went to the park."])
    assert "How was your weekend?" in block
    assert "I went to the park." in block
    assert dialogue._repeat_block([], []) == ""


def test_bilingual_coercion_rejects_ascii() -> None:
    """D5: 中文侧含 ASCII 字母 = 不可信 -> 置空; 纯中文照收 (不引入 re / CJK 白名单).

    实现收口在 ``mission_engine.generate_turn`` 里 (那两个页面共用的那一次调用), 所以自由
    对话与实战轮共用同一条纪律 —— 这条只断实现本身。
    """
    assert me.coerce_bilingual("你好呀") == "你好呀"
    assert me.coerce_bilingual("   ") == ""
    assert me.coerce_bilingual("Hello 你好") == ""
    assert me.coerce_bilingual('{"reply_cn": "x"}') == ""


def test_scene_messages_include_description_and_persona() -> None:
    """§0 第二条缺陷: 旧 prompt 只给 ``scene.title`` —— 现在 description 也进 system.

    §3 C3b 起 ``_scene_messages`` 收**已解析的场景对象** (目录/custom 同一个入口),
    本用例用 ``resolve_scene`` 精确命中目录 —— "静默回落第一条"的兜底已删, 未知 id 会
    返回 ``None``, 这里顺带钉它不会把 custom 前缀当成目录。
    """
    scene = dialogue_scenes.resolve_scene("ordering_coffee")
    assert scene is not None
    messages = dialogue._scene_messages(scene, [], [])
    system = messages[0]
    assert system.role == "system"
    assert scene.title in str(system.content)
    assert scene.description in str(system.content)
    # §3 B6: 扩容后人设也在 system 里 (persona/user_role 是 prompt 素材, 不是展示兜底)。
    assert scene.persona in str(system.content)
    assert scene.user_role in str(system.content)
    # 末尾指令带着共用形状与禁重复要求 (走的是 mission_engine 的那一份常量)。
    tail = str(messages[-1].content)
    assert me.GENERATION_JSON_SHAPE in tail and me.ANTI_REPEAT_RULES in tail
