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
    #: 英文卡片标题 (自定义场景没有 -> 显式传空 = 那一行不渲染, D5/§4 选择器).
    title_en: str
    #: 英文卡片描述.
    description_en: str
    #: AI 扮演的角色 (中文人设, prompt 素材).
    persona: str
    #: 学员扮演的角色 (中文).
    user_role: str
    #: 议程推进方向 (3-6 条, 中文; 空 = 沿用旧版通用议程指令).
    beats: tuple[str, ...]
    #: 开场候补 (≥2 句英文; 与 ``opening`` 分开是因为选择器只播第一句).
    openings: tuple[str, ...]
    #: 学员示范句素材 (≥2 句英文, **只进 prompt**, 不得当 fallback 回显).
    suggestions: tuple[str, ...]
    #: 细粒度情境 (自定义场景的 context_cn 落点: 卡片展示走 ``description``,
    #: prompt 素材走这里; 静态目录的描述本身已含情境, 故这一格**保留默认** ——
    #: 目录素材没有独立的 context 可填, B6 的"删默认逼漏填"对它不适用)。
    context: str = ""


#: 目录场景素材 (§3 B6)。**填完全员已删默认值** —— 新增场景漏填任何一个素材字段,
#: mypy 与构造期都会直接报错, 这是"素材不许缺"的机器门 (计划 §7-3: 先加默认值、
#: 填完 9 个场景、再删默认值逼漏填)。唯一保留默认的是 ``context`` (它是自定义场景
#: ``context_cn`` 的落点; 静态目录的情境已含在 ``description`` 里, 这一格允许留空)。
_DEFAULT_SCENES: tuple[DialogueScene, ...] = (
    # 商务场景排在前面: 目标用户是职场人士, 选择器默认场景取第一个.
    DialogueScene(
        id="business_meeting",
        title="商务会议",
        description="开会时发表意见、回应同事的提议。",
        opening="Let's get started. What is your opinion on the new plan?",
        suggestion="From our perspective, the plan is workable, but we need more data.",
        title_en="Business Meeting",
        description_en="Share your opinion and respond to colleagues in a meeting.",
        persona="主持会议的项目负责人",
        user_role="在会上发言的项目成员",
        beats=(
            "先对新方案表态: 支持、保留还是反对",
            "说出一条具体的理由或数据",
            "接住同事的反问或不同意见",
            "认领下一步行动和时间点",
        ),
        openings=(
            "Let's get started. What is your opinion on the new plan?",
            "Before we go around the table: how do you feel about the timeline?",
        ),
        suggestions=(
            "From our perspective, the plan is workable, but we need more data.",
            "I agree with the direction, but I have one concern about the budget.",
            "Could you give me until Friday to check with my team?",
        ),
    ),
    DialogueScene(
        id="work_report",
        title="工作汇报",
        description="向上级或客户汇报项目进展。",
        opening="Could you walk me through the progress of the project?",
        suggestion="We have finished the first phase, and we are on schedule.",
        title_en="Work Report",
        description_en="Report project progress to your manager or client.",
        persona="听汇报的上级或客户",
        user_role="汇报进展的项目负责人",
        beats=(
            "讲清楚做到哪一步了",
            "给出进度: 按时、提前还是落后",
            "说明遇到的一个问题和你的应对",
            "回答对方最关心的追问",
        ),
        openings=(
            "Could you walk me through the progress of the project?",
            "Let's start with the highlights since our last catch-up.",
        ),
        suggestions=(
            "We have finished the first phase, and we are on schedule.",
            "We are two days behind, but we can make it up this week.",
            "The main risk is supplier delivery, and we have a backup vendor.",
        ),
    ),
    DialogueScene(
        id="negotiation",
        title="商务谈判",
        description="就价格与合作条款进行谈判。",
        opening="Your price is a little higher than we expected. Can we talk about it?",
        suggestion="We can offer a five percent discount if you sign a two-year contract.",
        title_en="Business Negotiation",
        description_en="Negotiate price and terms with a potential partner.",
        persona="压价的合作方采购负责人",
        user_role="守住价格与条款的供应商代表",
        beats=(
            "接住对方对价格的异议",
            "解释价格背后的价值",
            "提出一个有条件让步的方案",
            "把条款谈成双方都能接受的形状",
        ),
        openings=(
            "Your price is a little higher than we expected. Can we talk about it?",
            "We like your proposal, but the numbers do not work for us yet.",
        ),
        suggestions=(
            "We can offer a five percent discount if you sign a two-year contract.",
            "Our price includes maintenance, which saves you cost in the long run.",
            "What budget are you working with? Maybe we can adjust the scope.",
        ),
    ),
    DialogueScene(
        id="daily_conversation",
        title="日常寒暄",
        description="和 AI 聊聊今天过得怎么样。",
        opening="Hi! How is your day going?",
        suggestion="My day is going well. I am practicing English.",
        title_en="Daily Chat",
        description_en="Chat about your day like a friend would.",
        persona="闲聊的朋友",
        user_role="练习日常对话的学员",
        beats=(
            "说说今天做了什么",
            "接住朋友分享的她自己的事",
            "把话题推进到周末或近期计划",
            "自然收尾, 约下次再聊",
        ),
        openings=(
            "Hi! How is your day going?",
            "Long time no talk! What have you been up to today?",
        ),
        suggestions=(
            "My day is going well. I am practicing English.",
            "It was busy but fun. I finished a big report today.",
            "How about you? Did you do anything interesting this weekend?",
        ),
    ),
    DialogueScene(
        id="ordering_coffee",
        title="点咖啡",
        description="在咖啡店用英语点单。",
        opening="Good morning! What would you like to order?",
        suggestion="I would like a small coffee, please.",
        title_en="Ordering Coffee",
        description_en="Order drinks and handle follow-up questions at a coffee shop.",
        persona="咖啡店店员",
        user_role="点单的顾客",
        beats=(
            "点出想要的饮品和大小",
            "接住店员的追加问题: 糖奶、冷热、堂食外带",
            "问一样你没喝过的东西或加购",
            "付款并收尾",
        ),
        openings=(
            "Good morning! What would you like to order?",
            "Hi, welcome! What can I get for you today?",
        ),
        suggestions=(
            "I would like a small coffee, please.",
            "A medium latte with oat milk, to go.",
            "How much is that altogether? Card, please.",
        ),
    ),
    DialogueScene(
        id="job_interview",
        title="求职面试",
        description="模拟面试自我介绍与能力问答。",
        opening="Welcome. Could you tell me a little about yourself?",
        suggestion="I am a careful and hardworking person who enjoys learning.",
        title_en="Job Interview",
        description_en="Practice self-introduction and competency questions.",
        persona="面试官 (HR 或部门经理)",
        user_role="来面试的候选人",
        beats=(
            "自我介绍: 背景与现在做的事",
            "讲一个你负责过的项目或成果",
            "回答你的优点和一个不足",
            "反问面试官一个问题收尾",
        ),
        openings=(
            "Welcome. Could you tell me a little about yourself?",
            "Thanks for coming in. Let us start with your background.",
        ),
        suggestions=(
            "I am a careful and hardworking person who enjoys learning.",
            "In my last role I led a team of four and shipped the project on time.",
            "Could you tell me what success looks like in this role?",
        ),
    ),
    DialogueScene(
        id="travel",
        title="机场值机",
        description="模拟在机场柜台办理登机。",
        opening="Hello. May I see your passport, please?",
        suggestion="Of course. Here is my passport.",
        title_en="Airport Check-in",
        description_en="Check in at the airport counter and answer routine questions.",
        persona="值机柜台工作人员",
        user_role="办理登机的旅客",
        beats=(
            "出示护照并说明目的地航班",
            "托运行李: 件数与超重问答",
            "提出座位偏好并接住追问",
            "拿登机牌并确认登机口和时间",
        ),
        openings=(
            "Hello. May I see your passport, please?",
            "Good afternoon, checking in for Flight CA 981? May I see your ID?",
        ),
        suggestions=(
            "Of course. Here is my passport.",
            "I have one suitcase to check in, please.",
            "Could I have a window seat if possible?",
        ),
    ),
    DialogueScene(
        id="shopping",
        title="商场购物",
        description="在店里咨询尺码和颜色。",
        opening="Hi there! Can I help you find something?",
        suggestion="Yes, I am looking for a blue shirt in medium size.",
        title_en="Shopping for Clothes",
        description_en="Ask about sizes, colors, fitting rooms and prices in a store.",
        persona="服装店导购",
        user_role="来买衣服的顾客",
        beats=(
            "说清要买什么: 品类、颜色、尺码",
            "接住店员推荐并追问细节",
            "要求试穿或换尺码",
            "问价格与退换, 决定买或走",
        ),
        openings=(
            "Hi there! Can I help you find something?",
            "Welcome! Are you looking for anything in particular today?",
        ),
        suggestions=(
            "Yes, I am looking for a blue shirt in medium size.",
            "Do you have this in a smaller size?",
            "Can I try it on? Where is the fitting room?",
        ),
    ),
    DialogueScene(
        id="doctor",
        title="看医生",
        description="向医生描述症状。",
        opening="Good morning. What seems to be the problem?",
        suggestion="I have had a headache for three days.",
        title_en="Seeing a Doctor",
        description_en="Describe symptoms and understand simple medical advice.",
        persona="门诊医生",
        user_role="来看病的患者",
        beats=(
            "说清症状和持续了多久",
            "回答医生的追问: 程度、诱因、病史",
            "听诊断并按住关键问: 吃药禁忌与复查",
            "确认下一步: 挂号、休息或检查",
        ),
        openings=(
            "Good morning. What seems to be the problem?",
            "Tell me what brings you in today. How long have you felt unwell?",
        ),
        suggestions=(
            "I have had a headache for three days.",
            "It hurts most in the morning, and I barely slept last night.",
            "Should I come back if it does not get better?",
        ),
    ),
)


def list_scenes() -> list[DialogueScene]:
    """Return every scene the Android picker can show."""
    return list(_DEFAULT_SCENES)


def resolve_scene(scene_id: str) -> DialogueScene | None:
    """按 id 精确命中目录; 未知名返回 ``None`` —— **没有**"静默当第一个场景"的兜底。

    旧版 ``get_scene`` 对任何拼错的 id 回落到 ``business_meeting`` (顺序是"目录第一
    条"), 于是乱拼 id 的学员被教成"商务会议"而界面毫无提示 (§3 C3b 点名删除):
    调用方拿到 ``None`` 一律 404 ``SCENE_NOT_FOUND`` (自定义 ``custom_<id>`` 的归属
    判定在 ``api/v1/dialogue.py``, 不在此模块 —— 这里保持纯静态素材, 不知道 DB)。
    """
    for scene in _DEFAULT_SCENES:
        if scene.id == scene_id:
            return scene
    return None
