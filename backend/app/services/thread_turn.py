"""v3.0 群聊单轮的 prompt 与语言判定.

台词生成本身仍然只有**一次** LLM 调用 —— :func:`mission_engine.generate_turn`,
与实战轮共用同一个 ``_judge`` 收口、同一组 ``GEN_*`` 常量。本模块只负责**拼 prompt**:
把"这场都有谁、议程走到哪、刚才聊了什么、学员这句是什么语言"摊给模型。

放在独立模块而不是路由里, 是因为这几段文本是最容易被改坏又最难从行为上发现的东西
(一句"要求学员讲英文"就足以让整条链路对初学者不可用), 它需要被直接单测钉住。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from app.services import dialogue_scenes, mission_engine, thread_store
from app.services.llm_provider import LlmMessage

#: 学员说了中文 (转写里出现汉字) —— 这一轮**不跑**英文逐词 ISE。
SPOKE_ZH = "zh"
#: 学员这句没有汉字, 按英文处理。
SPOKE_EN = "en"

_CJK_RANGES: tuple[tuple[int, int], ...] = (
    (0x4E00, 0x9FFF),  # 中日韩统一表意文字 (基本区)
    (0x3400, 0x4DBF),  # 扩展 A
    (0xF900, 0xFAFF),  # 兼容表意文字
)


def contains_cjk(text: str) -> bool:
    """转写文本里是否出现汉字."""
    return any(start <= ord(ch) <= end for ch in text for start, end in _CJK_RANGES)


def detect_spoke(text: str) -> str:
    """**事后**从转写文本判学员说了哪种语言.

    为什么不是事前: 讯飞 IAT 的 ``language`` 必须在送音频之前定死, 而实测
    ``zh_cn`` 原生吃中英混读 (方案 S2.4, ``scripts/smoke_iat_lang.py``), 所以听写只走
    一条 ``zh_cn`` 路, 语言在拿到文本之后才判 —— 零额外调用、零额外时延。

    判出来的结果只影响一件事: 要不要跑英文逐词发音分 (ISE)。
    """
    return SPOKE_ZH if contains_cjk(text) else SPOKE_EN


def _roster_block(scene: dialogue_scenes.DialogueScene) -> str:
    lines = []
    for role in scene.roles:
        persona = role.persona_cn or role.persona
        lines.append(f"- {role.role_id} = {role.name}: {persona}")
    return (
        "本场 AI 角色 (每轮的 speaker 只能填下面这些 id 之一):\n"
        + "\n".join(lines)
        + f"\n- 学员扮演: {scene.user_role}\n"
    )


def _agenda_block(scene: dialogue_scenes.DialogueScene, beat_index: int) -> str:
    if not scene.beats:
        return ""
    lines = []
    for number, beat in enumerate(scene.beats, 1):
        mark = "已聊" if number <= beat_index else "待聊"
        lines.append(f"{number}. [{mark}] {beat[: mission_engine.LINE_MAX_CHARS]}")
    return (
        "## 议程\n" + "\n".join(lines) + "\n"
        "按议程往下走, 聊过的方向不回头。若学员这句**确实推进了**下一条, 就在 next_beat "
        '里原样回显那一条的编号 (如 "3"); 没推进就留空字符串。\n'
    )


def _transcript_block(doc: dict[str, Any], *, limit: int = 10) -> str:
    """最近若干条气泡摊成对话文本 (角色台词 + 学员原话), 供模型接话。"""
    rows = []
    for message in thread_store.messages_of(doc)[-limit:]:
        kind = message.get("kind")
        if kind == thread_store.KIND_LINE:
            rows.append(f"教练({message.get('role_id')}): {str(message.get('text') or '')[:200]}")
        elif kind == thread_store.KIND_USER:
            spoken = str(message.get("recognized_text") or message.get("text") or "")
            rows.append(f"学员: {spoken[:200]}")
    return "\n".join(rows)


def learner_utterance(doc: dict[str, Any]) -> str:
    """这一轮要回应的那句话 (doc 里最后一条 user 气泡)."""
    for message in reversed(thread_store.messages_of(doc)):
        if message.get("kind") == thread_store.KIND_USER:
            return str(message.get("recognized_text") or message.get("text") or "")
    return ""


def turn_messages(
    scene: dialogue_scenes.DialogueScene,
    doc: dict[str, Any],
    learner_text: str,
) -> list[LlmMessage]:
    """群聊一轮的 prompt: 角色表 + 议程 + 最近对话 + 学员这句.

    与自由对话旧链路 (:func:`app.api.v1.dialogue._scene_messages`) 的关键差别有两条,
    两条都是**行为契约**而非措辞偏好:

    1. **学员可以说中文** —— 明确禁止"要求学员讲英文""请再说一遍英文"这类话。
       这是"保持场景对话流畅"的落地方式 (方案 S2.4 已裁决: 角色听得懂中文)。
    2. **每轮要交一个 speaker** —— 群聊里谁开口决定头像与音色。
    """
    shape = mission_engine._json_shape(
        mission_engine.GENERATION_FIELDS + mission_engine.GROUP_GENERATION_EXTRA_FIELDS
    )
    system = (
        "你是情景对话里的教练角色组, 学员是中文母语、能读写但开口少的英语初学者 (CEFR A2-B1)。"
        "场景: 「"
        + scene.title
        + "」 —— "
        + scene.description
        + "。"
        + _roster_block(scene)
        + (f"情境: {scene.context}。" if scene.context else "")
        + _agenda_block(scene, int(doc.get("beat_index") or 0))
        + mission_engine.GENERATION_RULES
        + mission_engine.ANTI_REPEAT_RULES
        + " 学员刚说的可能是中文, 也可能是英文: **照常理解并用英文继续推进**, "
        "不要要求学员说英文、不要纠错、不要停下来教语法。"
        " speaker 填本轮开口的那个角色 id (可以换人说话, 也可以连续同一人)。" + "\n\n" + shape
    )
    transcript = _transcript_block(doc)
    history = [LlmMessage(role="user", content=f"已经聊过的:\n{transcript}")] if transcript else []
    return [
        LlmMessage(role="system", content=system),
        *history,
        LlmMessage(role="user", content=f"学员刚说: {learner_text}"),
    ]


def resolve_speaker(
    scene: dialogue_scenes.DialogueScene, speaker_id: str
) -> dialogue_scenes.SceneRole:
    """把模型给的 speaker 落到一个真实角色上.

    模型拼错 id 时回落**本场第一个角色** —— 这不是"静默兜底"那种被删掉的坑: 台词已经
    生成好了, 只是没人知道该挂谁的头像, 让它有个头像有段声音比画一个空气泡好。
    (被删掉的是"拿不到台词就回放目录句" —— 那是冒充了一次不存在的生成。)
    """
    return scene.role_of(speaker_id) or scene.first_role


def beat_cursor_after(beat_index: int, scene: dialogue_scenes.DialogueScene, next_beat: str) -> int:
    """议程游标只能**前进且不超过末尾**; 模型回显了没听过/越界的编号就当没推进。"""
    raw = next_beat.strip()
    if not raw.isdigit():
        return beat_index
    target = int(raw)
    if target <= beat_index or target > len(scene.beats):
        return beat_index
    return target


def recent_suggestions(doc: dict[str, Any], *, limit: int = 8) -> Sequence[str]:
    """已经上屏过的建议英文 (反重复: 服务器对台词无状态, 只有会话里知道给过什么)。"""
    out: list[str] = []
    for message in thread_store.messages_of(doc):
        if message.get("kind") == thread_store.KIND_HINT:
            text = str(message.get("text") or "").strip()
            if text:
                out.append(text)
    return tuple(out[-limit:])
