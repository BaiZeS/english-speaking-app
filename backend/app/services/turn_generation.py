"""台词生成 + 转写锚定发音分 —— v3.0 对话链路仅剩的两件引擎活.

这里曾经叫 ``mission_engine``, 装着实战轮、判分、复盘报告、润色四件事。单词/课程/
打基础/测评退役之后, 只有这两件还有读者:

* :func:`generate_turn` —— 一条请求里**唯一**那次 LLM 调用 (台词 + 双语 + 建议句)。
  群聊轮 (``dialogue_threads``) 与自定义场景骨架 (``scene_spec_generator``) 共用这一份
  schema 与这组参数, 所以温度/token/超时/形状没有第二份可以漂移的副本。
* :func:`anchored_pronunciation` —— 学员**主动说英文**时, 拿 IAT 转写当 ISE 参考文本
  打发音分。

台词**没有**确定性降级可言: 拿不到就抛 :class:`LlmUnavailableError`, 端点回 503 且
这一轮不落库、不前进 (D5) —— 回放剧本正是"每轮同一句"的根因。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from app.config import settings
from app.models.schema import WordScore
from app.scoring.read_along import score_read_along
from app.services.audio_input import speech_rate_from_recognition
from app.services.drill_grader import (
    GEN_LLM_TIMEOUT_S,
    GEN_TURN_BUDGET_S,
    LlmUnavailableError,
    _judge,
)
from app.services.interfaces import ASRProvider
from app.services.llm_provider import (
    LlmMessage,
    no_thinking_body,
    resolve_roleplay_model,
)
from app.services.xunfei_asr import XunfeiASRProvider

# ====== 常量 ======

#: **台词生成** (一条请求里**唯一**的那次 LLM) 的输出预算与温度.
#: 旧形状把台词 + 润色 + 两个分 + 任务重判塞进一个 JSON (``TURN_MAX_TOKENS=700``),
#: 实测吐 ~1000 字 / p50 22.5s —— 生产 8 轮 7 轮撞 15s 墙 (§0 根因一). 拆开后 160 就够.
GEN_MAX_TOKENS = 160
#: 台词的温度必须**显式**给: 旧 ``judge_turn`` 不传它, 于是落进 :func:`_judge` 的判分
#: 默认 0.2 —— 用判分温度写台词是"AI 反复问同一类问题"的第二个成因 (§0 第二条缺陷).
GEN_TEMPERATURE = 0.7


#: 自由产出可用的讯飞 ISE 凭据口径 (与 ``XunfeiASRProvider.recognize`` 的自检等价;
#: 这里提前判断, 没凭据就**不调用** —— 回声 95 分不进证据).
def xunfei_ise_configured() -> bool:
    """讯飞 ISE 是否真的配了凭据 (决定转写锚定发音分是否产出)."""
    return bool(settings.xunfei_app_id and settings.xunfei_api_key and settings.xunfei_api_secret)


#: 生产 ISE 单例: 测试 monkeypatch 这个模块属性 (同 drill_grader 风格).
_ISE: ASRProvider = XunfeiASRProvider()


class TurnGeneration(BaseModel):
    """请求内唯一一次 LLM 的产物: 台词 + 双语 + 学员那句的中文对照 (§A1/D4).

    所有字段可缺省且上限照仓内既有中文口径 (500), 不自造一套; 空串表示"这一行不渲染"
    (D5: 绝不机翻占位)。

    后两个字段是 v3.0 群聊专用: 自定义场景骨架那条链路没有 roles 也没有议程游标,
    它的 prompt 不问这两格, 于是恒为默认空 —— 共用同一个类, 才有"一次调用不会漂成
    两份实现"的形状。
    """

    reply: str = Field(default="", max_length=500)
    reply_cn: str = Field(default="", max_length=500)
    suggestion: str = Field(default="", max_length=500)
    suggestion_cn: str = Field(default="", max_length=500)
    learner_cn: str = Field(default="", max_length=500)
    #: 本轮开口角色的 ``SceneRole.role_id`` (群聊); 其他链路留空。
    speaker: str = Field(default="", max_length=8)
    #: 学员这句把议程推进到哪一条 (回显 beats 原文; 没推进留空)。
    next_beat: str = Field(default="", max_length=160)

    @field_validator("reply", "reply_cn", "suggestion", "suggestion_cn", "learner_cn")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()

    @field_validator("speaker", "next_beat")
    @classmethod
    def _strip_group(cls, v: str) -> str:
        return v.strip()


#: 台词生成**必填之外还该产出**的字段清单 —— JSON 形状由它拼, 不许再手写第二份字面量
#: (两处各写一段形状就是漂移的开始, 见 §A4 的裁决)。
GENERATION_FIELDS: tuple[str, ...] = (
    "reply",
    "reply_cn",
    "suggestion",
    "suggestion_cn",
    "learner_cn",
)
#: v3.0 群聊在这五格之外多问两格 (谁说这句 / 议程推进到哪)。
GROUP_GENERATION_EXTRA_FIELDS: tuple[str, ...] = ("speaker", "next_beat")


def json_shape(fields: Sequence[str]) -> str:
    body = ", ".join(f'"{name}": "..."' for name in fields)
    return f"只输出 JSON: {{{body}}}"


#: 五字段形状 (非群聊链路用)。
GENERATION_JSON_SHAPE = json_shape(GENERATION_FIELDS)

#: 生成侧的行为要求, 公开给每条台词链路复用 (同一份, 不许各写一套)。
GENERATION_RULES = (
    "只输出一个 JSON 对象, 不要解释、不要 markdown 围栏。要求: "
    "(1) reply: 用英文说下一句 (1-2 句, A2-B1 词汇), 必须带一个追问或新信息, "
    "把对话往**没聊过的方向**推, 别提前结束; "
    "(2) reply_cn: reply 的简体中文意思; "
    "(3) suggestion: 给学员下一句可直接开口的示范英文; "
    "(4) suggestion_cn: suggestion 的简体中文意思; "
    "(5) learner_cn: 学员刚说的那句话的简体中文意思 (原文是中文就照其意思给英文侧的"
    "示范, 原文是英文就翻成中文)。"
)

#: **反重复的硬要求** (§A5): 所有台词链路共用一句话 —— 各写一份就一定会漂 (一处说
#: "换句式"、另一处只说"别说一样的"), 而它正是"AI 反复问同一类问题"的那道闸。
ANTI_REPEAT_RULES = "**不得同义复写**: 换新信息、换角度、换句式 —— 同一句话换个说法再说一遍就是失败"

#: 一句台词/示范/学员原话进 prompt 的字符上限 (**所有链路共用**: 群聊的 transcript 与
#: 议程块都引它)。不截的话, 一条超长的模型输出会把后续每一轮的 prompt 都撑大
#: (prefill 成本随历史线性涨)。
LINE_MAX_CHARS = 200


def coerce_bilingual(text: str) -> str:
    """双语字段的**可信度**门 (§A4/D5): 中文侧出现 ASCII 字母就算不可信 -> 置空.

    为什么: 模型偶尔把 ``reply_cn`` 写成英文 (或中英混排), 那一行渲染出来就是"中文"
    标签下的英文 —— 比缺行更糟 (D5: 缺字段 = 那一行不渲染, 绝不机翻占位)。判定只用最
    朴素的字符范围扫。

    收口在 :func:`generate_turn` 里 (所有台词链路共用这一份), 所以同一条纪律没有第二份
    可以漂移的实现。
    """
    cleaned = text.strip()
    if not cleaned:
        return ""
    if any("a" <= ch.lower() <= "z" for ch in cleaned):
        return ""
    return cleaned[:500]


def _bilingual_generation(judgement: TurnGeneration) -> TurnGeneration:
    """把字段里的三处中文过一遍可信度门 (台词/示范本身是英文, 不过门)."""
    return judgement.model_copy(
        update={
            "reply_cn": coerce_bilingual(judgement.reply_cn),
            "suggestion_cn": coerce_bilingual(judgement.suggestion_cn),
            "learner_cn": coerce_bilingual(judgement.learner_cn),
        }
    )


async def generate_turn(
    messages: Sequence[LlmMessage],
    *,
    model_id: str | None = None,
) -> tuple[TurnGeneration, str]:
    """**请求内唯一一次 LLM**: 台词 + 双语 (§A1/D1), 走 :func:`_judge` 的唯一收口.

    收 **messages** 而不是场景对象: 各条链路自己拼 prompt, 但温度/token/超时/schema
    全在这一处, 没有第二份可以漂移的副本。

    返回 ``(generation, llm_source)``。所有参数显式给:

    * ``model=resolve_roleplay_model(model_id)`` —— 生成是**纯文本**用途, 可以跟随
      客户端选的模型 (D2);
    * ``timeout=GEN_LLM_TIMEOUT_S(10)`` < ``hard_budget_s=GEN_TURN_BUDGET_S(14)``:
      单次 socket 先炸, 坏 JSON 的回喂重试才真落在墙钟里 (旧形状 socket 20 > 墙钟 15,
      一次尝试就吃穿整轮);
    * ``extra_body=no_thinking_body()`` —— 关掉 Qwen3 系的隐藏思考 token (实测占掉
      一半墙钟; 开关默认 false / ``.env`` 未设时返回 None, 调用形状不变)。

    **拿不到台词就抛** :class:`LlmUnavailableError` (未配置/超时/两次都不合规/无 reply):
    D5 —— 端点回 503、这一轮不落库不前进, 绝不回放剧本、绝不机翻占位。
    """
    resolved = resolve_roleplay_model(model_id)
    judgement = await _judge(
        TurnGeneration,
        messages,
        max_tokens=GEN_MAX_TOKENS,
        temperature=GEN_TEMPERATURE,
        model=resolved,
        timeout=GEN_LLM_TIMEOUT_S,
        hard_budget_s=GEN_TURN_BUDGET_S,
        extra_body=no_thinking_body(),
    )
    if not judgement.reply:
        # schema 宽容 (字段都可缺省), 但"没有台词"不等于"这一轮发生了" —— 端点那边
        # 一旦放行就会渲染一个空气泡, 所以在这里按不可用收口。
        raise LlmUnavailableError("台词生成结果里没有 reply")
    return _bilingual_generation(judgement), resolved


@dataclass(frozen=True)
class AnchoredPronunciation:
    """自由产出的转写锚定 ISE 结果 (ref == IAT 转写)."""

    pronunciation: float
    fluency: float
    completeness: float
    speech_rate_wpm: float
    word_details: list[WordScore]


async def anchored_pronunciation(
    audio_bytes: bytes,
    transcript: str,
    *,
    asr: ASRProvider | None = None,
) -> AnchoredPronunciation | None:
    """学员主动说英文时的发音证据: ISE 以 **转写为参考文本** 打分.

    纪律 (§5.6 + T3 landmine):
    * 没配讯飞凭据 -> 直接 None (StubASR 拿自己吐的文本当 ref 恒 95, 是回声);
    * 配了但结果 ``source != "xunfei"`` (调用失败回退) -> None + WARNING:
      **宁可发音维度空缺, 不造假的发音证据**。
    流利度用 :func:`app.scoring.read_along.score_read_along` 的现成综合
    (ISE fluency + speech_rate_wpm)。

    说中文的那一轮**根本不会走到这里** —— 英文 ISE 对中文音频没有意义, 调用方按转写
    文本判过语言才决定跑不跑 (方案 S2.4)。
    """
    if not audio_bytes or not transcript.strip():
        return None
    if not xunfei_ise_configured():
        return None
    provider = asr or _ISE
    result = await provider.recognize(audio_bytes, transcript, category="read_sentence")
    if result.source != "xunfei":
        logger.warning("anchored ISE fell back to stub; dropping pronunciation evidence")
        return None
    wpm = speech_rate_from_recognition(result.recognized, audio_bytes)
    scored = score_read_along(ref_text=transcript, asr=result, speech_rate_wpm=wpm, pause_count=0)
    return AnchoredPronunciation(
        pronunciation=scored.pronunciation,
        fluency=scored.fluency,
        completeness=scored.completeness,
        speech_rate_wpm=round(wpm, 1),
        word_details=list(scored.word_details),
    )
