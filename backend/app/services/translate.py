"""长按翻译 (v3.0, 方案 S2.7) —— 只在**没有现成双语**的文本上才被调用.

角色台词与建议回答在生成时就带了 ``text`` / ``text_cn`` 成对字段, 那些气泡长按是
客户端本地切换, 一次网络请求都不发。这里服务的是剩下的那一半: 学员自己说的那句中文
(听写出来的) 想看看英文该怎么讲。

诚实边界: 翻译失败**不机翻占位、不静默回显原文** —— 把原文当译文显示出去, 学员会
以为那就是"这句的英文说法", 比不翻更糟。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.services.drill_grader import TRANSLATE_BUDGET_S, LlmUnavailableError, _judge
from app.services.llm_provider import LlmMessage, no_thinking_body
from app.services.thread_turn import contains_cjk

#: 一条待翻文本的长度上限 (照台词/示范句同一口径, 不自造一套)。
MAX_CHARS = 500

TARGET_ZH = "zh"
TARGET_EN = "en"
TARGETS: tuple[str, ...] = (TARGET_ZH, TARGET_EN)


class Translation(BaseModel):
    """模型的唯一合法出口: 只给译文, 不给解释."""

    translated: str = Field(default="", max_length=MAX_CHARS)

    @field_validator("translated")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


def translate_messages(text: str, target: str) -> list[LlmMessage]:
    """翻译 prompt.

    进这里的一定是**没有现成对照**的文本 (有对照的客户端本地切), 所以要求模型
    翻得口语、翻得短 —— 它是拿来当"这句英文该怎么讲"的示范读的, 不是文学翻译。
    """
    into = "简体中文" if target == TARGET_ZH else "natural, simple American English (CEFR A2-B1)"
    system = (
        "你是英语口语陪练App里的翻译器。"
        f"把用户给的这句话翻成{into}。硬约束: "
        "(1) 只翻, 不解释、不加注音、不加引号、不用 markdown; "
        "(2) 翻成要**口语、短句**, 因为学员会照着念; "
        "(3) 原文里的数字、人名、菜名、时间照原样保留, 不要意译成描述; "
        '(4) 只输出 JSON: {"translated": "..."}'
    )
    return [
        LlmMessage(role="system", content=system),
        LlmMessage(role="user", content=text[:MAX_CHARS]),
    ]


async def translate_text(text: str, target: str) -> str:
    """翻一句; LLM 不可用/超时/输出不合格 -> :class:`LlmUnavailableError`.

    调用方 (路由) 把它翻成 503 —— 这里**绝不**回一个空串或原文冒充"翻好了"。
    """
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("translate_text needs non-blank text")
    if target not in TARGETS:
        raise ValueError(f"target must be one of {TARGETS}, got {target!r}")

    judgement = await _judge(
        Translation,
        translate_messages(cleaned, target),
        max_tokens=200,
        temperature=0.2,
        hard_budget_s=TRANSLATE_BUDGET_S,
        extra_body=no_thinking_body(),
    )
    translated = judgement.translated
    if not translated:
        raise LlmUnavailableError("翻译结果为空")
    # 方向自检: 要中文却给出一整句没有汉字的文本, 或要英文却给出纯中文 —— 那是模型
    # 把原文当译文吐回来了。这种"看起来成功"的输出比失败更难查, 按不可用收口。
    if target == TARGET_ZH and not contains_cjk(translated):
        raise LlmUnavailableError(f"目标中文却没有汉字: {translated[:40]!r}")
    if target == TARGET_EN and contains_cjk(translated) and translated.strip() == cleaned:
        raise LlmUnavailableError("英文目标却原样回显中文")
    return translated
