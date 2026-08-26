"""Catalog of free-dialogue scenes.

Lives in its own module so ``/dialogue/scenes`` can advertise the catalog
without dragging in the LLM/dialogue router code, and so future
operators can override scenes via env or DB without touching routing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueScene:
    id: str
    title: str
    description: str
    opening: str
    suggestion: str
    next_suggestion: str
    fallback_reply: str  # 用于 LLM 拿不到时的 deterministic 下一轮回答


_DEFAULT_SCENES: tuple[DialogueScene, ...] = (
    # 商务场景排在前面: 目标用户是职场人士, 选择器默认场景取第一个.
    DialogueScene(
        id="business_meeting",
        title="商务会议",
        description="开会时发表意见、回应同事的提议。",
        opening="Let's get started. What is your opinion on the new plan?",
        suggestion="From our perspective, the plan is workable, but we need more data.",
        next_suggestion="I suggest we set up a small team to look into the risks.",
        fallback_reply="Good point. Could you explain the main risk in more detail?",
    ),
    DialogueScene(
        id="work_report",
        title="工作汇报",
        description="向上级或客户汇报项目进展。",
        opening="Could you walk me through the progress of the project?",
        suggestion="We have finished the first phase, and we are on schedule.",
        next_suggestion="The next step is testing. We expect to finish it by Friday.",
        fallback_reply="Sounds good. Are there any issues blocking the team?",
    ),
    DialogueScene(
        id="negotiation",
        title="商务谈判",
        description="就价格与合作条款进行谈判。",
        opening="Your price is a little higher than we expected. Can we talk about it?",
        suggestion="We can offer a five percent discount if you sign a two-year contract.",
        next_suggestion="Let's meet in the middle. We can also include free training.",
        fallback_reply="That is a fair offer. What about the delivery schedule?",
    ),
    DialogueScene(
        id="daily_conversation",
        title="日常寒暄",
        description="和 AI 聊聊今天过得怎么样。",
        opening="Hi! How is your day going?",
        suggestion="My day is going well. I am practicing English.",
        next_suggestion="I am going to finish my work and read a book tonight.",
        fallback_reply="That is great to hear! What are you going to do next?",
    ),
    DialogueScene(
        id="ordering_coffee",
        title="点咖啡",
        description="在咖啡店用英语点单。",
        opening="Good morning! What would you like to order?",
        suggestion="I would like a small coffee, please.",
        next_suggestion="Milk, please, but no sugar.",
        fallback_reply="Sure. Would you like milk or sugar with that?",
    ),
    DialogueScene(
        id="job_interview",
        title="求职面试",
        description="模拟面试自我介绍与能力问答。",
        opening="Welcome. Could you tell me a little about yourself?",
        suggestion="I am a careful and hardworking person who enjoys learning.",
        next_suggestion="I am good at communicating clearly and solving problems.",
        fallback_reply="Thank you. What is one skill you are proud of?",
    ),
    DialogueScene(
        id="travel",
        title="机场值机",
        description="模拟在机场柜台办理登机。",
        opening="Hello. May I see your passport, please?",
        suggestion="Of course. Here is my passport.",
        next_suggestion="I am checking in one suitcase.",
        fallback_reply="Thank you. How many bags are you checking in today?",
    ),
    DialogueScene(
        id="shopping",
        title="商场购物",
        description="在店里咨询尺码和颜色。",
        opening="Hi there! Can I help you find something?",
        suggestion="Yes, I am looking for a blue shirt in medium size.",
        next_suggestion="Do you have it in a different color?",
        fallback_reply="Sure. What size are you looking for?",
    ),
    DialogueScene(
        id="doctor",
        title="看医生",
        description="向医生描述症状。",
        opening="Good morning. What seems to be the problem?",
        suggestion="I have had a headache for three days.",
        next_suggestion="It gets worse in the afternoon.",
        fallback_reply="I see. Let me ask a few questions about your symptoms.",
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
