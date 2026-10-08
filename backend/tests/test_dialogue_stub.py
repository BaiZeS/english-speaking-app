"""自由对话的**无凭据**面 (§A4/D5): 目录还在, 但"没凭据就回一句话"那条路没了.

§A4 之前 ``/dialogue/turn`` 在没有凭据时返回 200 + ``status="stub"``: 第一轮回
``scene.fallback_reply``, 第二轮起永远是写死的 ``"Thanks for sharing. Could you tell me a
little more?"``。那不只是"降级"——它是**冒充生成**: 界面看起来像模型说的, 而那句话与学员
说的话无关 (§0 根因三)。D5 之后同一条路是 **503** (端点明说不可用), 所以本文件钉三件事:

* 场景目录 (``/dialogue/scenes``) 与开场白 (``/dialogue/generate``) **不**受 D5 影响 ——
  它们本来就有确定性目录可兜 (开场白是"这一页的静态素材", 不是对学员话的回应);
* ``/dialogue/turn`` 无凭据 -> 503 ``TURN_GENERATION_UNAVAILABLE``, 且**没有**任何台词;
* 有凭据时回的是**台词那一半** (含双语), 润色/分数恒为 null (它们在请求外, §A1/D1)。
"""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import drill_grader as dg
from app.services import llm_provider
from app.services import mission_engine as me
from tests.test_drill_grader import install_llm
from tests.test_mission import generation_json


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> None:
    llm_provider.reset_llm_provider_for_tests()
    yield  # type: ignore[misc]
    llm_provider.reset_llm_provider_for_tests()


@pytest.mark.asyncio
async def test_dialogue_generate_still_uses_the_local_catalog() -> None:
    """开场白不走 D5: 目录里的 opening 是**静态素材**, 没有它就整页打不开。"""
    payload = {"scene": "ordering_coffee", "mode": "k12"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "lines" in data
    assert isinstance(data["lines"], list)
    assert data["status"] == "stub"


@pytest.mark.asyncio
async def test_dialogue_turn_without_credentials_is_a_503() -> None:
    """D5: 没有凭据 -> 503, **不是** 200 + 目录里的下一句."""
    payload = {
        "scene_id": "ordering_coffee",
        "history": [{"role": "user", "text": "Hi"}],
        "user_audio_b64": "AAAA",
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 503, r.text
    body = r.json()
    # 码与文案收在 ``drill_grader.turn_generation_unavailable`` 一份 (两个端点共用):
    # 抄两份的话改一处就会漏一处, 客户端码表 (按 code 命中中文) 也跟着前后不一致。
    assert body["error"]["code"] == dg.TURN_GENERATION_UNAVAILABLE_CODE
    assert body["error"]["message"] == dg.turn_generation_unavailable().message
    assert "reply_text" not in body  # 没有伪造的气泡


@pytest.mark.asyncio
async def test_dialogue_generate_includes_opening_and_suggested_reply() -> None:
    payload = {"scene": "ordering_coffee", "mode": "adult"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/generate", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "点咖啡"
    assert data["lines"][0]["role"] == "assistant"
    assert data["suggested_reply"]


@pytest.mark.asyncio
async def test_dialogue_turn_returns_bilingual_reply_and_suggestion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """有凭据: 一次调用给出**五字段** (台词 + 双语), 润色/分数诚实缺席 (§A4/D1)."""
    install_llm(
        monkeypatch,
        generation=[
            generation_json(
                reply="Good morning! What can I get you?",
                reply_cn="早上好, 您要点什么",
                suggestion="A latte, please.",
                suggestion_cn="请给我一杯拿铁。",
                learner_cn="你好。",
            )
        ],
    )
    payload = {
        "scene_id": "ordering_coffee",
        "history": [
            {"role": "assistant", "text": "Good morning!"},
            {"role": "user", "text": "I would like coffee."},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "ready"
    assert data["reply_text"] == "Good morning! What can I get you?"
    assert data["suggested_reply"] == "A latte, please."
    assert data["reply_cn"] == "早上好, 您要点什么"
    assert data["suggestion_cn"] == "请给我一杯拿铁。"
    assert data["learner_cn"] == "你好。"
    # 判分/润色不在本条请求里 (§A1/D1): 字段保留, 值诚实缺席。
    assert data["polish"] is None
    assert data["grammar_score"] is None and data["vocabulary_score"] is None
    assert data["llm_source"] == "qwen3.8-max"


@pytest.mark.asyncio
async def test_dialogue_turn_never_repeats_what_it_already_said(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§A5 反重复: prompt 里必须带"已经说过的台词 + 已展示的参考句 + 别同义复写".

    服务端自己不留历史 (自由对话没有会话表), 所以 Coach 台词从请求 history 取、
    参考句靠客户端 echo 的 ``shown_suggestions`` —— 这条断言读的是真发出去的 prompt。
    """
    fake = install_llm(monkeypatch, generation=[generation_json()])
    payload = {
        "scene_id": "daily_conversation",
        "history": [
            {"role": "assistant", "text": "How was your weekend?"},
            {"role": "user", "text": "It was nice."},
        ],
        "shown_suggestions": ["I went to the park.", "I stayed home and read."],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200, r.text
    prompt = "\n".join(str(m["content"]) for m in fake.requests[0]["messages"])
    assert "How was your weekend?" in prompt  # 历史 assistant 回合 = 已说过的台词
    assert "I went to the park." in prompt  # 客户端 echo 的参考句
    assert me.ANTI_REPEAT_RULES in prompt  # 反重复硬要求 = 两页共用的那一份常量
    assert "ONE short follow-up question" not in prompt  # 旧 prompt 的固定句式已删


@pytest.mark.asyncio
async def test_dialogue_turn_keeps_native_message_roles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§A4: 历史按**原生 messages 数组**传 (system + user/assistant 交替), 不再压成一段文本."""
    fake = install_llm(monkeypatch, generation=[generation_json()])
    payload = {
        "scene_id": "daily_conversation",
        "history": [
            {"role": "user", "text": "Hi there."},
            {"role": "assistant", "text": "Hello! How are you?"},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    assert r.status_code == 200, r.text
    roles = [m["role"] for m in fake.requests[0]["messages"]]
    assert roles[0] == "system"
    assert roles[1:3] == ["user", "assistant"]
    assert all(m["content"].strip() for m in fake.requests[0]["messages"])


@pytest.mark.asyncio
async def test_monolingual_reply_cn_is_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    """D5: 中文侧出现 ASCII 字母 = 不可信 -> 置空 (宁可那一行不渲染, 不机翻占位)."""
    install_llm(
        monkeypatch,
        generation=[
            generation_json(
                reply="What did you do last night?",
                reply_cn="What did you do last night?",  # 模型把中文写成了英文
                suggestion="I watched a movie.",
                suggestion_cn="我看了一部电影。",
                learner_cn="",  # 模型没给 -> 保持空
            )
        ],
    )
    payload = {"scene_id": "daily_conversation", "history": [{"role": "user", "text": "Hi"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        r = await c.post("/api/v1/dialogue/turn", json=payload)
    data = r.json()
    assert data["reply_cn"] == ""  # 含 ASCII 字母 -> 不可信
    assert data["suggestion_cn"] == "我看了一部电影。"
    assert data["learner_cn"] == ""
