"""Catalog of free-dialogue scenes.

Lives in its own module so ``/dialogue/scenes`` can advertise the catalog
without dragging in the LLM/dialogue router code, and so future
operators can override scenes via env or DB without touching routing.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DialogueScene:
    """一个场景的**静态素材**: 卡片展示 (中/英) + 人设/议程/开场与示范素材.

    ``opening`` 与 ``suggestion`` 仍然有消费者 (``/dialogue/generate`` 的确定性开场 +
    客户端的参考回答卡), 所以留着。而 ``next_suggestion`` / ``fallback_reply`` 这对
    "LLM 拿不到时照本宣科" 的兜底字段在 §A4/D5 之后**没有任何读者** (拿不到台词就是 503,
    不再回放目录), 已删 —— 别再把它们加回来: 一个场景只有一句兜底句, 用两轮就会重复
    (那正是学员报的"AI 反复问同一句")。

    §A5/B6 扩容 (§3 C2 的自定义场景投影也走同一形状, 见
    ``scene_spec_generator.dialogue_scene_view``):

    * ``title_en``/``description_en`` —— 计划 D4 的「建议英文」展示面 (§4 场景选择器);
    * ``persona``/``user_role`` —— 这场里 AI 演谁 / 学员演谁 (中文人设, 进台词 prompt);
    * ``beats`` —— 议程: 对话按什么方向推进 (§A5「议程推进」的素材本体);
    * ``openings`` —— **≥2 条**开场候补: 只有一句开场 = 每次进来同一句 (§0 同族缺陷);
    * ``suggestions`` —— 学员侧示范句素材 (≥2; **只供进 prompt 取材, 不许当兜底句回显**)。

    ⚠ 本模块刻意**不知道** job 表与场景骨架长什么样 (静态素材, 无 DB 形状), 这样
    ``dialogue_scenes`` 与 ``scene_courses`` 两条生成管线解耦的边界才有形状可守。
    """

    id: str
    title: str
    description: str
    opening: str
    suggestion: str
    #: 英文卡片标题 (自定义场景没有, 空 = 那一行不渲染, D5/§4 选择器).
    title_en: str = ""
    #: 英文卡片描述.
    description_en: str = ""
    #: AI 扮演的角色 (中文人设, prompt 素材).
    persona: str = ""
    #: 学员扮演的角色 (中文).
    user_role: str = ""
    #: 议程推进方向 (3-6 条, 中文; 空 = 沿用旧版通用议程指令).
    beats: tuple[str, ...] = ()
    #: 开场候补 (≥2 句英文; 与 ``opening`` 分开是因为选择器只播第一句).
    openings: tuple[str, ...] = ()
    #: 学员示范句素材 (≥2 句英文, **只进 prompt**, 不得当 fallback 回显).
    suggestions: tuple[str, ...] = ()
    #: 细粒度情境 (自定义场景的 context_cn 落点: 卡片展示走 ``description``,
    #: prompt 素材走这里; 静态目录的描述本身已含情境, 故这一格允许留空).
    context: str = ""


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
