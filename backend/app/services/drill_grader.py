"""LLM 调用的**唯一**收口: 一次调用 + 坏 JSON 回喂重试 1 次 + 预算封顶.

v3.0 大扫除之后这里只剩下"怎么安全地调一次结构化 LLM"这件事。打基础四题型判分
(retell / translate / make_sentence / sentence)、read_along 评分、润色、能力画像证据
都随各自的端点一起退役了 —— 它们服务的功能已经从产品里删除, 不是搬去别处。

留下的东西都有多个现役读者: 台词生成 (``turn_generation``)、每轮评分作业
(``thread_grading``)、长按翻译 (``translate``)、自定义场景骨架
(``scene_spec_generator``)。它们共用同一个 :func:`_judge`, 所以"超时怎么算、坏输出
怎么办、拿不到怎么收口"在全仓只有一份实现。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, cast

from loguru import logger
from pydantic import BaseModel, ValidationError

from app.core.errors import AppError
from app.services.llm_provider import LlmMessage, get_llm_provider

PASS_SCORE = 60.0


LLM_TIMEOUT_S = 20.0
LLM_MAX_TOKENS = 400

GEN_LLM_TIMEOUT_S = 10.0
GEN_TURN_BUDGET_S = 14.0

GRADING_TURN_BUDGET_S = 45.0


TRANSLATE_BUDGET_S = 6.0


SCENE_BRIEF_JOB_BUDGET_S = 45.0


_J = TypeVar("_J", bound=BaseModel)


class LlmUnavailableError(Exception):
    """LLM 判分不可用 (未配置 / 调用失败 / 重试一次后输出仍不合规)."""

    def __init__(self, reason: str, *, not_configured: bool = False) -> None:
        super().__init__(reason)
        self.not_configured = not_configured

    @property
    def label(self) -> str:
        """降级反馈的前缀 —— 诚实告诉学员这是占位分."""
        return "LLM 未配置:" if self.not_configured else "LLM 判分失败:"


#: 台词生成不可用的错误码 (§A6/D5). 两个对话端点 (实战轮 / 自由对话轮) 共用它。
TURN_GENERATION_UNAVAILABLE_CODE = "TURN_GENERATION_UNAVAILABLE"

#: 学员看到的那句话 (§A6)。**一份**, 因为线上 APK 侧的码表按 code 命中这条中文:
#: 两处各写一遍就会漂 (一处改了另一处不变 = 同一种故障两种说法)。
_TURN_GENERATION_UNAVAILABLE_CN = "AI 台词生成不可用（模型超时或未配置），这一轮没有发生，请重试"  # noqa: RUF001


def turn_generation_unavailable() -> AppError:
    """台词生成不可用 -> 503 (§A6 的**唯一**收口: 实战轮与自由对话轮共用).

    为什么要有这个工厂而不是各写一遍 ``AppError(503, …)``: 文案里那句中文与码是客户端码表的
    键 (``BackendErrorText.sessionErrorCodeText``), 抄两份就一定会漂。照仓内既有风格放在
    :class:`LlmUnavailableError` 旁边 —— 它正是这条 503 的**因**, 而且两个调用点都从这个模块
    引东西, 不新增任何模块依赖。
    """
    return AppError(503, _TURN_GENERATION_UNAVAILABLE_CN, TURN_GENERATION_UNAVAILABLE_CODE)


# ====== 1) read_along: 复用 /score 的 ISE 管线 ======


_JSON_FENCE_RE = re.compile(r"^```[A-Za-z0-9_-]*\s*|\s*```\s*$")


def _truncate(value: str, limit: int) -> str:
    cleaned = " ".join(value.split())
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"


def _parse_llm_json(text: str) -> dict[str, Any]:
    """容错解析 LLM 该返回的 JSON 对象 (§5.5 统一模式).

    先剥 markdown 围栏; ``json.loads`` 失败再退一步取第一个 ``{`` 到最后一个 ``}``
    的切片 —— 模型总爱在 JSON 前后加解说句. 拿不到对象才抛, 交给 :func:`_judge` 做
    "错误回喂重试一次".
    """
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = _JSON_FENCE_RE.sub("", candidate).strip()
    data: Any
    try:
        data = json.loads(candidate)
    except json.JSONDecodeError:
        start, end = candidate.find("{"), candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("输出里找不到 JSON 对象") from None
        try:
            data = json.loads(candidate[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON 解析失败: {exc}") from None
    if not isinstance(data, dict):
        raise ValueError("输出不是 JSON 对象")
    return cast("dict[str, Any]", data)


def _resolve_judge_model() -> str:
    """判分用的模型 id, 跟随 ``LLM_DEFAULT_MODEL`` (本机已切 qwen3.8-max).

    drill 判分**不让客户端选模型**: 判分口径必须在一门课内稳定, 否则同课不同步的
    分数没法比较, 也没法拿去更新画像.
    """
    provider = get_llm_provider()
    return cast(str, getattr(provider, "default_model", "") or "") or "llm"


async def _judge(
    schema: type[_J],
    messages: Sequence[LlmMessage],
    *,
    max_tokens: int = LLM_MAX_TOKENS,
    model: str | None = None,
    timeout: float = LLM_TIMEOUT_S,
    temperature: float = 0.2,
    hard_budget_s: float | None = None,
    extra_body: Mapping[str, Any] | None = None,
) -> _J:
    """一次 LLM 判分 + 容错解析; 输出不合规则**回喂校验错误重试 1 次**.

    未配置 -> ``LlmUnavailableError(not_configured=True)``; 传输异常 / 二次仍不合规
    -> ``LlmUnavailableError``. 调用方一律降级到确定性启发式.

    ``hard_budget_s``: **整个调用 (含坏 JSON 的重试那一次) 的墙钟硬预算**, 同步 HTTP
    路径必填 —— 取值与求和见模块顶部的硬预算块. 用 ``asyncio.wait_for`` 封顶, 并且
    **在这里**就把 ``TimeoutError`` 翻成 ``LlmUnavailableError``: 同步调用点
    (``_graded_text_step`` / ``mission_engine.review_copy`` 的同步入口
    ``build_review_report`` / ``mission_engine.polish_text`` /
    ``mission_engine.generate_turn`` / ``assessment_engine.judge_level``) 只
    ``except LlmUnavailableError``, 让裸
    ``TimeoutError`` 逃逸会把"降级"变成 500, 比不封顶更糟. 反过来, 只把 ``timeout=``
    调小是没用的: 那只是单次尝试的上限.

    ``mission_engine.review_copy`` 是**唯一两处共用一个 LLM 入口**的先例 (同步组合
    ``build_review_report`` 给 ``REVIEW_LLM_BUDGET_S``, 后台作业
    ``run_review_copy_job`` 给 ``REVIEW_COPY_JOB_BUDGET_S``): 该函数自己**不给默认预算**,
    预算必须由调用点报出来, 上面那条 AST 扫描 + ``tests/test_latency_budget.py`` 一起
    守着. 转换点仍然只有这里一处, 所以两条路的降级分支写法完全一样.

    P3 起该模式被 mission/polish/dialogue 复用 (见 ``app.services.mission_engine``):
    ``max_tokens`` 给更大的综合 JSON 留预算; ``model`` **只允许纯文本用途**
    (润色) 传入覆盖 —— 判分/任务判定恒用服务端默认模型 (``_resolve_judge_model``),
    调用方不许拿客户端选的模型污染分数。P4 起课程生成也走同一模式, 但生成的
    JSON 大得多 (整课骨架/剧本 ~2000 token), ``timeout`` / ``temperature`` 给它
    放宽 (默认值保持判分口径, 判分调用方一个字都不用改)。``hard_budget_s`` 留给
    同步路径: 生成作业**不给**, 30s 的读超时对它不成立 (后台作业 + 前端轮询).
    """
    provider = get_llm_provider()
    if not cast(bool, getattr(provider, "is_configured", False)):
        raise LlmUnavailableError("LLM 未配置 (缺 LLM_API_KEY)", not_configured=True)
    resolved_model = model or _resolve_judge_model()

    async def _ask(turns: Sequence[LlmMessage]) -> str:
        completion = await provider.chat(
            model=resolved_model,
            messages=turns,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_body=extra_body,
        )
        return completion.content

    async def _attempts() -> _J:
        """1 次调用 + 坏 JSON 回喂重试 1 次; 两次都不合规就到此为止 (移动端不等第二分钟)."""
        turns = list(messages)
        try:
            raw = await _ask(turns)
        except Exception as exc:  # 网络/超时/provider 未就绪: 不在学员身上重试
            raise LlmUnavailableError(f"LLM 调用失败: {exc}") from exc

        error_text = ""
        try:
            return schema.model_validate(_parse_llm_json(raw))
        except (ValueError, ValidationError) as first_error:
            error_text = _truncate(str(first_error), 300)
            logger.warning("drill judgement malformed, retrying once | err={}", error_text)

        retry_turns = [
            *turns,
            LlmMessage(role="assistant", content=_truncate(raw, 1200)),
            LlmMessage(
                role="user",
                content=(
                    f"上一条输出不合格 ({error_text}). "
                    "严格按要求的字段名与类型重发, 只输出那个 JSON 对象, 不要任何多余文字."
                ),
            ),
        ]
        try:
            raw2 = await _ask(retry_turns)
            return schema.model_validate(_parse_llm_json(raw2))
        except ValidationError as exc:
            raise LlmUnavailableError(f"重试一次后字段仍不合规: {exc}") from exc
        except Exception as exc:  # JSON 仍坏 / 调用又失败: 到此为止, 降级
            raise LlmUnavailableError(f"重试一次后输出仍不可用: {exc}") from exc

    if hard_budget_s is None:
        return await _attempts()
    try:
        return await asyncio.wait_for(_attempts(), timeout=hard_budget_s)
    except TimeoutError as exc:
        # 唯一一处超时→降级的转换点: 调用方的 ``except LlmUnavailableError`` 因此
        # 一个字都不用改 (mission 轮的 ``judge_turn`` 也顺手接住它).
        raise LlmUnavailableError(
            f"超出 {hard_budget_s:.0f}s 硬预算 (同步请求封顶, 见 drill_grader 硬预算块)"
        ) from exc
