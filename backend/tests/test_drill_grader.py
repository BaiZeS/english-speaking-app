"""``_judge`` 的行为契约 + 全仓共用的假 LLM 骨架 (``install_llm``).

``install_llm`` 把 ``AsyncOpenAI`` 换成按 **prompt 形状**路由的假客户端。路由而不是
按顺序吐料, 是因为一条请求里可能有多条 LLM 路 (群聊台词 + 后台判分), 先后顺序在测试里
不稳定 —— 按形状各给一份料, 断言就不依赖调用顺序。

v3.0 大扫除删掉了打基础四题型 (read_along/retell/translate/make_sentence) 与润色的
判分, 那些用例随之删除; 留在这里的是**仍然服役**的那一个收口 ``_judge`` 的语义:
一次调用 + 坏 JSON 回喂错误重试 1 次 + 再坏就抛 ``LlmUnavailableError``。
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from typing import Any, ClassVar

import pytest
from loguru import logger

from app.services import drill_grader as dg
from app.services import llm_provider
from app.services.translate import Translation
from app.services.turn_generation import TurnGeneration


@pytest.fixture(autouse=True)
def _reset_llm_provider() -> Iterator[None]:
    llm_provider.reset_llm_provider_for_tests()
    yield
    llm_provider.reset_llm_provider_for_tests()


@pytest.fixture
def warnings_sink() -> Iterator[list[str]]:
    """抓 loguru 的 WARNING (降级与重试必须留痕, 不然线上悄悄出问题没人知道)."""
    bag: list[str] = []
    sink_id = logger.add(lambda message: bag.append(str(message)), level="WARNING")
    yield bag
    logger.remove(sink_id)


class _FakeCompletions:
    def __init__(self, client: _FakeOpenAI) -> None:
        self._client = client

    async def create(self, **kwargs: Any) -> Any:
        self._client.requests.append(kwargs)
        reply = self._client.next_reply(kwargs)
        if isinstance(reply, Exception):
            raise reply

        class _Msg:
            content: ClassVar[str] = ""

        message = _Msg()
        message.content = reply  # type: ignore[attr-defined]

        class _Choice:
            pass

        choice = _Choice()
        choice.message = message  # type: ignore[attr-defined]

        class _Resp:
            pass

        resp = _Resp()
        resp.choices = [choice]  # type: ignore[attr-defined]
        resp.model = "qwen3.8-max"  # type: ignore[attr-defined]
        return resp


class _FakeChat:
    def __init__(self, client: _FakeOpenAI) -> None:
        self.completions = _FakeCompletions(client)


#: prompt 里的**形状标记**: §A1 之后一轮有两次调用 (生成侧 / 判分侧) 外加收工时的总评文案,
#: 各自的 JSON 形状里有对方没有的键 —— 用它们路由, 用例就不必猜"谁先被调到"。
#: ``scene`` (§3 C2) 是第四条: 自定义场景骨架作业, 形状里独有的 ``"opener_cn"`` 键
#: 与上面三个互斥 (整课骨架用 ``opening_a_cn``, 不会撞)。
_GENERATION_SHAPE_MARKER = '"reply_cn"'
_GRADING_SHAPE_MARKER = '"polish"'
_REVIEW_SHAPE_MARKER = '"highlights"'
_SCENE_SHAPE_MARKER = '"opener_cn"'
#: v3.0 会话线程的每轮评分形状 (三轴 + 是否推进议程)。
_THREAD_GRADING_SHAPE_MARKER = '"relevance"'


def _prompt_text(kwargs: Mapping[str, Any]) -> str:
    """请求里的 prompt 全文 (provider 把 ``LlmMessage`` 转成了 ``{"role","content"}`` 字典)."""
    messages = kwargs.get("messages") or []
    parts: list[str] = []
    for message in messages:
        if isinstance(message, Mapping):
            parts.append(str(message.get("content") or ""))
        else:
            parts.append(str(getattr(message, "content", "")))
    return "\n".join(parts)


class _FakeOpenAI:
    """替掉 ``llm_provider.AsyncOpenAI``: 按 prompt 形状路由, 再退回脚本.

    路由存在的理由 (§A1 拆调用之后): 一轮实战 = 请求内的 ``generate_turn`` +
    后台作业里的 ``judge_turn``, 两条路的先后**在测试里不稳定** (作业由用例自己 await
    驱动, 也可能根本没跑)。按 prompt 里的形状标记各给一份料, 断言就不依赖调用顺序。

    ``replies`` 是**旧口径**的脚本 (按顺序吐, 最后一条无限重复), 保留它是因为大多数用例
    只调一条路; 形状队列 (``generation`` / ``grading``) 命中时优先。
    """

    def __init__(
        self,
        replies: list[Any],
        *,
        generation: list[Any] | None = None,
        grading: list[Any] | None = None,
        review: list[Any] | None = None,
        scene: list[Any] | None = None,
        thread_grading: list[Any] | None = None,
    ) -> None:
        self._replies = list(replies)
        self._generation = list(generation or [])
        self._grading = list(grading or [])
        self._review = list(review or [])
        self._scene = list(scene or [])
        self._thread_grading = list(thread_grading or [])
        self.requests: list[dict[str, Any]] = []
        self.chat = _FakeChat(self)

    def next_reply(self, kwargs: Mapping[str, Any]) -> Any:
        prompt = _prompt_text(kwargs)
        if _GENERATION_SHAPE_MARKER in prompt:
            shaped = self._generation
        elif _GRADING_SHAPE_MARKER in prompt:
            shaped = self._grading
        elif _REVIEW_SHAPE_MARKER in prompt:
            shaped = self._review
        elif _SCENE_SHAPE_MARKER in prompt:
            shaped = self._scene
        elif _THREAD_GRADING_SHAPE_MARKER in prompt:
            shaped = self._thread_grading
        else:
            shaped = []
        if shaped:
            return shaped.pop(0) if len(shaped) > 1 else shaped[0]
        if len(self._replies) > 1:
            return self._replies.pop(0)
        return self._replies[0] if self._replies else RuntimeError("no canned reply")

    def with_options(self, **kwargs: Any) -> _FakeOpenAI:
        self.options = kwargs  # type: ignore[attr-defined]
        return self


def install_llm(
    monkeypatch: pytest.MonkeyPatch,
    replies: list[Any] | None = None,
    *,
    generation: list[Any] | None = None,
    grading: list[Any] | None = None,
    review: list[Any] | None = None,
    scene: list[Any] | None = None,
    thread_grading: list[Any] | None = None,
) -> _FakeOpenAI:
    """配好"有 LLM 凭据"的环境并把客户端换成假的 (与 test_llm_endpoints 同套路).

    ``generation`` / ``grading`` / ``review`` / ``scene`` 按 prompt 形状路由 (见
    :class:`_FakeOpenAI`); ``replies`` 是给只调一条路的用例的旧脚本口径。
    """
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(settings, "llm_base_url", "https://example.test/v1")
    monkeypatch.setattr(settings, "llm_default_model", "qwen3.8-max")
    client = _FakeOpenAI(
        replies or [],
        generation=generation,
        grading=grading,
        review=review,
        scene=scene,
        thread_grading=thread_grading,
    )
    monkeypatch.setattr(llm_provider, "AsyncOpenAI", lambda **kwargs: client)
    llm_provider.reset_llm_provider_for_tests()
    return client


def _user_prompt(client: _FakeOpenAI, index: int = 0) -> str:
    return str(client.requests[index]["messages"][-1]["content"])


# ============================================================ _judge 的语义


def _turn_msgs() -> list[Any]:
    from app.services.llm_provider import LlmMessage

    return [LlmMessage(role="user", content="学员刚说: I want noodles")]


@pytest.mark.asyncio
async def test_good_json_is_one_call_and_keeps_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    client = install_llm(monkeypatch, [json.dumps({"reply": "Sure, what size?"})])
    got = await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert got.reply == "Sure, what size?"
    assert len(client.requests) == 1, "合规输出不该有第二次调用"


@pytest.mark.asyncio
async def test_bad_json_is_retried_once_with_the_error_fed_back(
    monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    """坏输出**回喂校验错误**重试一次 —— 这是本仓唯一的容错形状, 不许变成静默降级."""
    good = json.dumps({"reply": "Sure, what size?"})
    client = install_llm(monkeypatch, ["这不是 JSON", good])
    got = await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert got.reply == "Sure, what size?"
    assert len(client.requests) == 2
    retry_turns = client.requests[1]["messages"]
    assert retry_turns[-2]["role"] == "assistant" and retry_turns[-2]["content"] == "这不是 JSON"
    assert "上一条输出不合格" in retry_turns[-1]["content"]
    assert any("retrying once" in line for line in warnings_sink)


@pytest.mark.asyncio
async def test_validation_error_is_part_of_the_retry_feedback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    good = json.dumps({"translated": "好的"})
    bad = json.dumps({"translated": "x" * 900})  # 超 max_length
    install_llm(monkeypatch, [bad, good])
    got = await dg._judge(Translation, _turn_msgs(), hard_budget_s=5.0)
    assert got.translated == "好的"


@pytest.mark.asyncio
async def test_second_bad_output_raises_instead_of_inventing_content(
    monkeypatch: pytest.MonkeyPatch, warnings_sink: list[str]
) -> None:
    """两次都不合规 -> ``LlmUnavailableError``, **不造内容**。

    台词那条路上这翻成 503 且这一轮不落库 (D5)。旧形状在这里"回退到目录里的下一句",
    正是学员报的"AI 反复问同一句"的根因。
    """
    client = install_llm(monkeypatch, ["garbage one", "garbage two"])
    with pytest.raises(dg.LlmUnavailableError):
        await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert len(client.requests) == 2, "只重试一次, 不做第三次"


@pytest.mark.asyncio
async def test_transport_error_raises_without_retrying(monkeypatch: pytest.MonkeyPatch) -> None:
    """上游 5xx 不重喂 (SDK 重试已被关死, 再重试一次只会把时延翻倍)。"""
    client = install_llm(monkeypatch, [RuntimeError("upstream 502")])
    with pytest.raises(dg.LlmUnavailableError):
        await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert len(client.requests) == 1


@pytest.mark.asyncio
async def test_fenced_json_and_prose_wrappers_are_tolerated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_llm(monkeypatch, ['```json\n{"reply": "Two to go?"}\n```'])
    got = await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert got.reply == "Two to go?"


def test_parse_llm_json_edge_cases() -> None:
    assert dg._parse_llm_json('{"reply": "a"}') == {"reply": "a"}
    assert dg._parse_llm_json('```json\n{"reply": "b"}\n```') == {"reply": "b"}
    assert dg._parse_llm_json('好的, 这是结果:\n{"reply": "c"}\n希望有帮助') == {"reply": "c"}
    for bad in ("完全不像 JSON", "[1,2,3]", ""):
        with pytest.raises(ValueError):
            dg._parse_llm_json(bad)


def test_parse_llm_json_rejects_unparseable_object_slice() -> None:
    with pytest.raises(ValueError, match="找不到 JSON 对象"):
        dg._parse_llm_json('{"reply": ')
    with pytest.raises(ValueError, match="JSON 解析失败"):
        dg._parse_llm_json('结果如下 {"reply": "x",} 希望有帮助')


@pytest.mark.asyncio
async def test_no_credentials_raises_not_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """没配凭据也是 ``LlmUnavailableError`` 且带 ``not_configured`` —— 端点据此回 503."""
    from app.config import settings

    monkeypatch.setattr(settings, "llm_api_key", "")
    with pytest.raises(dg.LlmUnavailableError) as exc:
        await dg._judge(TurnGeneration, _turn_msgs(), hard_budget_s=5.0)
    assert exc.value.not_configured
