"""Catalog of free-dialogue scenes.

Lives in its own module so ``/dialogue/scenes`` can advertise the catalog
without dragging in the LLM/dialogue router code, and so future
operators can override scenes via env or DB without touching routing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueScene:
    """一个场景的**静态素材**: 标题/描述 (选择器卡片) + 开场白 + 一句参考句.

    ``opening`` 与 ``suggestion`` 仍然有消费者 (``/dialogue/generate`` 的确定性开场 +
    客户端的参考回答卡), 所以留着。而 ``next_suggestion`` / ``fallback_reply`` 这对
    "LLM 拿不到时照本宣科" 的兜底字段在 §A4/D5 之后**没有任何读者** (拿不到台词就是 503,
    不再回放目录), 已删 —— 别再把它们加回来: 一个场景只有一句兜底句, 用两轮就会重复
    (那正是学员报的"AI 反复问同一句")。
    """

    id: str
    title: str
    description: str
    opening: str
    suggestion: str


_DEFAULT_SCENES: tuple[DialogueScene, ...] = (
    # 商务场景排在前面: 目标用户是职场人士, 选择器默认场景取第一个.
    DialogueScene(
        id="business_meeting",
        title="商务会议",
        description="开会时发表意见、回应同事的提议。",
        opening="Let's get started. What is your opinion on the new plan?",
        suggestion="From our perspective, the plan is workable, but we need more data.",
    ),
    DialogueScene(
        id="work_report",
        title="工作汇报",
        description="向上级或客户汇报项目进展。",
        opening="Could you walk me through the progress of the project?",
        suggestion="We have finished the first phase, and we are on schedule.",
    ),
    DialogueScene(
        id="negotiation",
        title="商务谈判",
        description="就价格与合作条款进行谈判。",
        opening="Your price is a little higher than we expected. Can we talk about it?",
        suggestion="We can offer a five percent discount if you sign a two-year contract.",
    ),
    DialogueScene(
        id="daily_conversation",
        title="日常寒暄",
        description="和 AI 聊聊今天过得怎么样。",
        opening="Hi! How is your day going?",
        suggestion="My day is going well. I am practicing English.",
    ),
    DialogueScene(
        id="ordering_coffee",
        title="点咖啡",
        description="在咖啡店用英语点单。",
        opening="Good morning! What would you like to order?",
        suggestion="I would like a small coffee, please.",
    ),
    DialogueScene(
        id="job_interview",
        title="求职面试",
        description="模拟面试自我介绍与能力问答。",
        opening="Welcome. Could you tell me a little about yourself?",
        suggestion="I am a careful and hardworking person who enjoys learning.",
    ),
    DialogueScene(
        id="travel",
        title="机场值机",
        description="模拟在机场柜台办理登机。",
        opening="Hello. May I see your passport, please?",
        suggestion="Of course. Here is my passport.",
    ),
    DialogueScene(
        id="shopping",
        title="商场购物",
        description="在店里咨询尺码和颜色。",
        opening="Hi there! Can I help you find something?",
        suggestion="Yes, I am looking for a blue shirt in medium size.",
    ),
    DialogueScene(
        id="doctor",
        title="看医生",
        description="向医生描述症状。",
        opening="Good morning. What seems to be the problem?",
        suggestion="I have had a headache for three days.",
    ),
)


def list_scenes() -> list[DialogueScene]:
    """Return every scene the Android picker can show."""
    return list(_DEFAULT_SCENES)


def get_scene(scene_id: str) -> DialogueScene:
    """Resolve a scene by id, falling back to the first scene for unknown ids."""
    for scene in _DEFAULT_SCENES:
        if scene.id == scene_id:
            return scene
    return _DEFAULT_SCENES[0]
