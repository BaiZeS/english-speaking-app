"""Catalog of scenario-dialogue scenes.

Lives in its own module so ``/dialogue/scenes`` can advertise the catalog
without dragging in the LLM/dialogue router code, and so future
operators can override scenes via env or DB without touching routing.

v3.0 起一场戏是**一组角色**而不是单个 persona: 微信式群聊里每句台词都要落到某个
``role_id`` 上 (谁说的决定头像、昵称与 TTS 音色), 所以素材的最小单位从「一句话」
变成「一句话 + 一个说话人」。
"""

from __future__ import annotations

from dataclasses import dataclass

#: 合法 TTS 音色. 与 ``app.services.mimo_tts._KNOWN_VOICES`` 同源 —— 有测试逐字段钉死,
#: 加音色必须两处一起加, 否则目录里会出现一个合成时静默回落默认音色的角色。
VOICES: tuple[str, ...] = ("Mia", "Chloe", "Milo", "Dean")


@dataclass(frozen=True)
class SceneRole:
    """本场里的一个 AI 角色 (学员不算角色, 学员见 ``DialogueScene.user_role``)."""

    #: 台词的 ``speaker`` 取的就是它 —— 一旦发布不许改, 它已写进存量会话线程。
    role_id: str
    #: 气泡上显示的昵称 (中文, 按学员语言展示).
    name: str
    name_en: str
    #: 必须 ∈ :data:`VOICES`; 同一场内两个角色**不得**共用音色, 否则听不出是谁在说。
    voice: str
    #: 英文人设, 进台词 prompt.
    persona: str
    persona_cn: str


@dataclass(frozen=True)
class OpeningLine:
    """一句开场白: 说话人 + 英文 + 中文意思."""

    role_id: str
    text: str
    text_cn: str


@dataclass(frozen=True)
class SuggestionLine:
    """学员侧示范句素材 (只进 prompt 取材, **不许**当兜底句回显)."""

    text: str
    text_cn: str


@dataclass(frozen=True)
class DialogueScene:
    """一个场景的**静态素材**: 卡片展示 (中/英) + 角色/议程/开场与示范素材.

    ⚠ 本模块刻意**不知道** job 表与场景骨架长什么样 (静态素材, 无 DB 形状), 这样
    ``dialogue_scenes`` 与 ``scene_courses`` 两条生成管线解耦的边界才有形状可守。

    历史包袱: ``opening``/``suggestion``/``persona``/``openings``/``suggestions`` 这些
    单数/纯英文视图现在是 :data:`roles` 与 ``opening_lines``/``suggestion_lines`` 的
    **派生属性** —— 素材只有一份真相, 旧代码路径 (``/dialogue/generate``、老
    ``/dialogue/turn``、``scene_spec_generator``) 照旧读属性, 等 T8 删旧链路时
    这些派生器一起删。
    """

    id: str
    title: str
    description: str
    #: 英文卡片标题 (自定义场景没有 -> 显式传空 = 那一行不渲染, D5/§4 选择器).
    title_en: str
    #: 英文卡片描述.
    description_en: str
    #: 本场 AI 角色 (≥2, 音色互不重复).
    roles: tuple[SceneRole, ...]
    #: 学员扮演的角色 (中文).
    user_role: str
    #: 学员角色的英文写法.
    user_role_en: str
    #: 开场候补 (≥2 句, 各带说话人).
    opening_lines: tuple[OpeningLine, ...]
    #: 学员示范句素材 (≥2; **只供进 prompt 取材, 不许当兜底句回显**).
    suggestion_lines: tuple[SuggestionLine, ...]
    #: 议程推进方向 (3-6 条, 中文; 空 = 沿用旧版通用议程指令).
    beats: tuple[str, ...]
    #: 细粒度情境 (自定义场景的 context_cn 落点: 卡片展示走 ``description``,
    #: prompt 素材走这里; 静态目录的描述本身已含情境, 故这一格**保留默认** ——
    #: 目录素材没有独立的 context 可填)。
    context: str = ""

    # ---- 派生视图: 素材只有一份, 下面全是读法 ----

    @property
    def persona(self) -> str:
        """旧链路把 AI 侧当单 persona 用; 群聊里拼成一行."""
        return " / ".join(role.persona_cn for role in self.roles)

    @property
    def opening(self) -> str:
        return self.opening_lines[0].text if self.opening_lines else ""

    @property
    def suggestion(self) -> str:
        return self.suggestion_lines[0].text if self.suggestion_lines else ""

    @property
    def openings(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.opening_lines)

    @property
    def suggestions(self) -> tuple[str, ...]:
        return tuple(line.text for line in self.suggestion_lines)

    def role_of(self, role_id: str) -> SceneRole | None:
        """按 ``role_id`` 精确命中; 未知返回 ``None`` (**不回落第一个角色**)。"""
        for role in self.roles:
            if role.role_id == role_id:
                return role
        return None

    @property
    def first_role(self) -> SceneRole:
        """``speaker`` 判不出来时的落点 —— 是"这一场第一个角色", 不是"某个默认角色"。"""
        return self.roles[0]


#: 目录场景素材。**填完全员不得给默认值** —— 新增场景漏填任何一个素材字段,
#: mypy 与构造期都会直接报错, 这是"素材不许缺"的机器门。
#:
#: 样板是前两场 (餐厅点餐 / 咖啡店), 后面十场照同一形状填。每场的硬约束由
#: ``tests/test_dialogue_scenes.py`` 逐场钉死: roles≥2 且音色互不重复、
#: opening_lines≥2 且 role_id 都能在本场 roles 里命中、suggestion_lines≥2、
#: beats 3-6、中英两格都不许空白。
_DEFAULT_SCENES: tuple[DialogueScene, ...] = (
    DialogueScene(
        id="restaurant",
        title="餐厅点餐",
        description="和朋友去餐厅,点菜、问推荐、处理上错菜。",
        title_en="Ordering at a Restaurant",
        description_en="Order food with a friend, ask for a recommendation, fix a wrong dish.",
        roles=(
            SceneRole(
                role_id="r1",
                name="服务员 Sam",
                name_en="Waiter Sam",
                voice="Milo",
                persona="a friendly waiter taking an order, speaks slowly and offers one recommendation",
                persona_cn="热情的服务员,负责点单并推荐一道菜",
            ),
            SceneRole(
                role_id="r2",
                name="朋友小林",
                name_en="Friend Lin",
                voice="Chloe",
                persona="the learner's friend, deciding what to order and asking the learner's opinion",
                persona_cn="同行的朋友,拿不定主意、会问学员想吃啥",
            ),
        ),
        user_role="去餐厅吃饭的顾客",
        user_role_en="a customer having dinner out",
        opening_lines=(
            OpeningLine(
                role_id="r2",
                text="I could really go for something with noodles. What about you?",
                text_cn="我好想吃碗面,你想吃啥?",
            ),
            OpeningLine(
                role_id="r1",
                text="Hi, welcome! Are you ready to order, or do you need a minute?",
                text_cn="您好,欢迎光临!现在点单,还是再看一会儿?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="I'll have the beef noodles, and could I get the soup without cilantro?",
                text_cn="我要牛肉面,汤里请不要放香菜。",
            ),
            SuggestionLine(
                text="What do you recommend? I'm not very hungry.",
                text_cn="你有什么推荐?我不是很饿。",
            ),
        ),
        beats=(
            "和朋友商量想吃点什么,说出一条自己的偏好",
            "向服务员点单:主食、饮料、忌口至少说清一项",
            "接住服务员的推荐或追问,决定要不要",
            "处理一个小意外:上错菜、口味不对或要结账",
        ),
    ),
    DialogueScene(
        id="coffee_shop",
        title="咖啡店点单",
        description="在咖啡店点一杯喝的,问尺寸、加料,堂食还是外带。",
        title_en="At the Coffee Shop",
        description_en="Order a drink, ask about sizes and extras, choose in or to go.",
        roles=(
            SceneRole(
                role_id="r1",
                name="咖啡师 Ivy",
                name_en="Barista Ivy",
                voice="Mia",
                persona="a brisk barista who asks size, milk and take-away, and suggests one special",
                persona_cn="利落的咖啡师,会问尺寸、奶、堂食外带,并推荐一款特调",
            ),
            SceneRole(
                role_id="r2",
                name="常客 Mark",
                name_en="Regular Mark",
                voice="Dean",
                persona="a customer standing in line behind the learner, chatting about the menu",
                persona_cn="排在学员后面的常客,会搭话聊菜单",
            ),
        ),
        user_role="来买咖啡的顾客",
        user_role_en="a customer buying coffee",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Morning! What can I get you today?",
                text_cn="早上好!今天来点什么?",
            ),
            OpeningLine(
                role_id="r2",
                text="Their seasonal latte is surprisingly good. Have you tried it?",
                text_cn="他家那款季节限定拿铁意外地好喝,你试过吗?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="A medium latte with oat milk, please. To stay or to go? To go.",
                text_cn="中杯燕麦奶拿铁,外带,谢谢。",
            ),
            SuggestionLine(
                text="How big is your large, and is there a decaf option?",
                text_cn="你们的大杯是多大?有无咖啡因的选择吗?",
            ),
        ),
        beats=(
            "点一杯具体的饮品,说清尺寸",
            "补一句要求:换奶、加浓、少糖、去咖啡因任选其一",
            "回答堂食还是外带,并接住对方的搭话",
            "问一个小问题:价格、Wi-Fi、或推荐哪款",
        ),
    ),
    DialogueScene(
        id="airport_checkin",
        title="机场值机",
        description="坐飞机前到柜台值机:出示护照、托运行李、选座位、问登机口。",
        title_en="Airport Check-in",
        description_en="Check in at the airport counter: show your passport, drop your bags, pick a seat.",
        roles=(
            SceneRole(
                role_id="r1",
                name="值机柜台 Kelly",
                name_en="Check-in Agent Kelly",
                voice="Mia",
                persona="an airline check-in agent who verifies the passport, weighs the bags, and asks window or aisle",
                persona_cn="航空公司值机职员,核对护照、称行李,问靠窗还是过道",
            ),
            SceneRole(
                role_id="r2",
                name="行李柜台 Dave",
                name_en="Baggage Clerk Dave",
                voice="Milo",
                persona="the baggage desk staff who explains the weight limit and what can't be checked in",
                persona_cn="行李柜台职员,说明限重和哪些东西不能托运",
            ),
        ),
        user_role="赶飞机、正在值机的旅客",
        user_role_en="a passenger checking in for a flight",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Hi! Passport, please. Where are you flying today?",
                text_cn="您好!请出示护照。今天飞哪儿?",
            ),
            OpeningLine(
                role_id="r2",
                text="How many bags are you checking today?",
                text_cn="您今天托运几件行李?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="Just one bag. Is there a weight limit?",
                text_cn="就一件。有重量限制吗?",
            ),
            SuggestionLine(
                text="Could I get a window seat? I can keep my backpack with me, right?",
                text_cn="能给个靠窗的座位吗?背包我可以随身带,对吧?",
            ),
        ),
        beats=(
            "出示护照,说清目的地",
            "办托运:说件数、问限重",
            "选座位,或提一个特殊要求",
            "问登机口和登机时间,确认来得及",
        ),
    ),
    DialogueScene(
        id="hotel_checkin",
        title="酒店入住",
        description="到酒店前台办入住:报预订、拿房卡、问早餐和 Wi-Fi。",
        title_en="Hotel Check-in",
        description_en="Check in at the front desk: confirm your booking, get the key, ask about breakfast and Wi-Fi.",
        roles=(
            SceneRole(
                role_id="r1",
                name="前台 Amy",
                name_en="Receptionist Amy",
                voice="Chloe",
                persona="a hotel receptionist who looks up the booking, asks for ID, and explains breakfast and Wi-Fi",
                persona_cn="酒店前台,查订单、要证件,说明早餐和 Wi-Fi",
            ),
            SceneRole(
                role_id="r2",
                name="行李员 Tom",
                name_en="Bellhop Tom",
                voice="Milo",
                persona="a cheerful bellhop who offers to carry the bag and points out the elevator",
                persona_cn="热心的行李员,主动帮拿行李、指电梯位置",
            ),
        ),
        user_role="刚到店、要办入住的客人",
        user_role_en="a guest arriving at the hotel",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Welcome! Do you have a reservation with us?",
                text_cn="欢迎!您有预订吗?",
            ),
            OpeningLine(
                role_id="r2",
                text="Need a hand with that bag? The elevator's just over there.",
                text_cn="要我帮忙拿包吗?电梯就在那边。",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="Yes, under the name Li. Two nights, one double room.",
                text_cn="有的,预订人是李。两晚,一间大床房。",
            ),
            SuggestionLine(
                text="What time is breakfast? And how do I connect to the Wi-Fi?",
                text_cn="早餐几点?Wi-Fi 怎么连?",
            ),
        ),
        beats=(
            "报预订信息:姓名、几晚、房型",
            "递上证件,听前台讲入住须知",
            "问清一件具体的事:早餐、Wi-Fi 或洗衣",
            "提一个小请求:换房、加条毛巾、或说明会晚到",
        ),
    ),
    DialogueScene(
        id="doctor",
        title="看医生",
        description="去看病:说清症状、回答医生追问、听懂诊断和用药嘱咐。",
        title_en="Seeing the Doctor",
        description_en="Visit a clinic: describe your symptoms, answer questions, understand the diagnosis and the medicine.",
        roles=(
            SceneRole(
                role_id="r1",
                name="Reed 医生",
                name_en="Dr. Reed",
                voice="Mia",
                persona="a calm doctor who asks about symptoms, gives a simple diagnosis, and explains how to take the medicine",
                persona_cn="沉稳的医生,问症状、给简单诊断、交代怎么吃药",
            ),
            SceneRole(
                role_id="r2",
                name="护士 Kim",
                name_en="Nurse Kim",
                voice="Chloe",
                persona="a friendly nurse who takes the temperature and asks about allergies",
                persona_cn="亲切的护士,量体温、问过敏史",
            ),
        ),
        user_role="身体不舒服、来看病的病人",
        user_role_en="a patient visiting the clinic",
        opening_lines=(
            OpeningLine(
                role_id="r2",
                text="Good morning. Let's start with your temperature. Any allergies?",
                text_cn="早上好。先量个体温。有过敏吗?",
            ),
            OpeningLine(
                role_id="r1",
                text="Hello, I'm Dr. Reed. So, what doesn't feel right?",
                text_cn="你好,我是 Reed 医生。哪里不舒服?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="I've had a sore throat and a fever since last night.",
                text_cn="从昨晚开始,我嗓子疼,还发烧。",
            ),
            SuggestionLine(
                text="Is it serious? Should I take this medicine before or after meals?",
                text_cn="严重吗?这药是饭前吃还是饭后吃?",
            ),
        ),
        beats=(
            "说清症状:哪里不舒服、几天了",
            "回答追问:发不发烧、有无过敏、吃过什么药",
            "听诊断,追问禁忌:忌口、要不要休息",
            "确认下一步:药怎么吃、要不要复诊",
        ),
    ),
    DialogueScene(
        id="rental",
        title="租房看房",
        description="租房子看房:问房间和家具、算清费用、谈入住时间和条件。",
        title_en="Renting an Apartment",
        description_en="Tour a rental: ask about the rooms and furniture, sort out the costs, agree on the move-in terms.",
        roles=(
            SceneRole(
                role_id="r1",
                name="中介 Nora",
                name_en="Agent Nora",
                voice="Mia",
                persona="a rental agent who shows the flat, explains the lease, and talks about the deposit",
                persona_cn="带看房的中介,讲租约、谈押金",
            ),
            SceneRole(
                role_id="r2",
                name="房东 Grant",
                name_en="Landlord Grant",
                voice="Dean",
                persona="the owner of the flat who answers questions and decides the move-in date",
                persona_cn="房东,回答房子的问题、拍板入住时间",
            ),
        ),
        user_role="想找房子、来看房的租客",
        user_role_en="a tenant looking for a place to rent",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="You're here for the two-bedroom, right? Let's start with the kitchen.",
                text_cn="你是来看两居室的,对吧?先从厨房看起。",
            ),
            OpeningLine(
                role_id="r2",
                text="The rent is nine hundred a month. Any questions about the lease?",
                text_cn="房租一个月九百。租约有什么问题?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="Is Wi-Fi included in the rent, or do I pay for it myself?",
                text_cn="房租里含 Wi-Fi 吗,还是要我自己付?",
            ),
            SuggestionLine(
                text="Could I move in on the first? And when is the deposit due?",
                text_cn="我下个月一号能入住吗?押金什么时候交?",
            ),
        ),
        beats=(
            "边看边问:家具、采光、住几楼",
            "算清费用:房租、押金、水电网",
            "说明自己情况:几个人住、租多久、何时入住",
            "谈一个小条件:养宠物、修空调、或提前退租",
        ),
    ),
    DialogueScene(
        id="shopping",
        title="购物与退换货",
        description="商店买东西:问价、试尺码、砍砍价,或退换一件不合适的。",
        title_en="Shopping and Returns",
        description_en="Shop for something: ask the price, try a size, bargain a little, or exchange an item that doesn't work.",
        roles=(
            SceneRole(
                role_id="r1",
                name="店员 Ella",
                name_en="Sales Associate Ella",
                voice="Chloe",
                persona="a helpful shop assistant who finds sizes, states prices, and mentions the sale",
                persona_cn="热心的店员,找尺码、报价、顺便提促销",
            ),
            SceneRole(
                role_id="r2",
                name="店长 Ray",
                name_en="Store Manager Ray",
                voice="Milo",
                persona="the store manager who decides on returns and discounts within the rules",
                persona_cn="店长,按规定处理退换货和折扣",
            ),
        ),
        user_role="逛街买东西、要换货的顾客",
        user_role_en="a customer buying something and exchanging an item",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Hi! Are you looking for something in particular today?",
                text_cn="您好!今天有特别想找的东西吗?",
            ),
            OpeningLine(
                role_id="r2",
                text="You bought this here? Let me see the receipt.",
                text_cn="这是在我们店买的吗?我看看小票。",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="I love this jacket, but it's too small. Do you have a medium?",
                text_cn="我很喜欢这件夹克,但小了。有中号吗?",
            ),
            SuggestionLine(
                text="That's a bit over my budget. Could you give me a better price?",
                text_cn="有点超我预算了。能便宜点吗?",
            ),
        ),
        beats=(
            "说要买什么:款式、尺码、颜色",
            "问价格,嫌贵就试着砍一句",
            "办退换:说清原因、出示小票",
            "做决定:买下道谢,或礼貌走人",
        ),
    ),
    DialogueScene(
        id="asking_directions",
        title="问路",
        description="在路上找人问路:说清目的地、听懂方向、再确认一遍。",
        title_en="Asking for Directions",
        description_en="Stop someone on the street: say where you're going, follow the directions, confirm once more.",
        roles=(
            SceneRole(
                role_id="r1",
                name="路人 Grace",
                name_en="Passerby Grace",
                voice="Mia",
                persona="a friendly local who walks the learner through the directions step by step",
                persona_cn="友善的本地路人,一步一步指路",
            ),
            SceneRole(
                role_id="r2",
                name="店主 Leo",
                name_en="Shop Owner Leo",
                voice="Dean",
                persona="a shopkeeper who knows the area and suggests taking the bus instead",
                persona_cn="熟门的店主,会建议改坐公交",
            ),
        ),
        user_role="初来乍到、在街上问路的人",
        user_role_en="a visitor asking the way on the street",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="You look a little lost. Can I help?",
                text_cn="你好像有点迷路。需要帮忙吗?",
            ),
            OpeningLine(
                role_id="r2",
                text="The museum? Go straight, then turn left at the lights.",
                text_cn="去博物馆?直走,然后红绿灯那儿左转。",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="Excuse me, how do I get to the nearest subway station?",
                text_cn="打扰一下,最近的地铁站怎么走?",
            ),
            SuggestionLine(
                text="Sorry, did you say left or right? Is it far from here?",
                text_cn="抱歉,您刚才是说左转还是右转?离这儿远吗?",
            ),
        ),
        beats=(
            "开口问路:说出目的地",
            "听懂方向词:直走、左转、第二个路口",
            "没听懂就追问:哪边、远不远、坐几路车",
            "把自己听到的路线复述一遍确认,再道谢",
        ),
    ),
    DialogueScene(
        id="pickup",
        title="机场接人",
        description="去机场接一位外国同事:确认航班、在到达口等人、接到后带路。",
        title_en="Picking Someone Up at the Airport",
        description_en="Meet a colleague at the airport: check the flight, wait at arrivals, greet them, and lead the way out.",
        roles=(
            SceneRole(
                role_id="r1",
                name="客人 Chris",
                name_en="Visitor Chris",
                voice="Milo",
                persona="an overseas colleague who just landed and calls to find where to meet",
                persona_cn="刚落地的外国同事,打电话问在哪儿碰头",
            ),
            SceneRole(
                role_id="r2",
                name="问询处 Zoe",
                name_en="Info Desk Zoe",
                voice="Mia",
                persona="the airport info desk clerk who explains which gate to wait at",
                persona_cn="机场问询处职员,说明该在哪个口等",
            ),
        ),
        user_role="到机场接人的东道主",
        user_role_en="the host picking someone up at the airport",
        opening_lines=(
            OpeningLine(
                role_id="r2",
                text="Flight CA180? Arrivals is upstairs, gate four.",
                text_cn="CA180 航班?到达厅在楼上,四号口。",
            ),
            OpeningLine(
                role_id="r1",
                text="Hi, I just landed! Where exactly should I look for you?",
                text_cn="嗨,我刚落地!具体在哪儿能找到你?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="I'm at gate four, holding a sign with your name. Can you see it?",
                text_cn="我在四号口,举着有你名字的牌子。能看到吗?",
            ),
            SuggestionLine(
                text="Great to see you! How was your flight? The car is outside.",
                text_cn="见到你真好!一路怎么样?车就在外面。",
            ),
        ),
        beats=(
            "先问清楚:航班几点到、从哪个口出来",
            "在到达口等人,发消息对位置",
            "接到人:打招呼、问一路累不累",
            "带路出去:车在哪、要不要先放行李",
        ),
    ),
    DialogueScene(
        id="small_talk",
        title="交朋友闲聊",
        description="认识新朋友:自我介绍、聊爱好和周末、约下次再聚。",
        title_en="Making Small Talk",
        description_en="Meet a new friend: introduce yourself, chat about hobbies and weekends, plan to hang out again.",
        roles=(
            SceneRole(
                role_id="r1",
                name="新同学 Sara",
                name_en="Classmate Sara",
                voice="Mia",
                persona="an outgoing classmate who starts a chat about hobbies and weekends",
                persona_cn="外向的新同学,从爱好和周末聊起",
            ),
            SceneRole(
                role_id="r2",
                name="同学 Joe",
                name_en="Classmate Joe",
                voice="Milo",
                persona="a relaxed classmate who joins in and asks about food and hometown",
                persona_cn="随和的同学,加入话头,问吃的和老家",
            ),
        ),
        user_role="刚来、想多交点朋友的新同学",
        user_role_en="a newcomer who wants to make friends",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Hey! Is this seat free? I'm Sara.",
                text_cn="嗨!这个座位有人吗?我叫 Sara。",
            ),
            OpeningLine(
                role_id="r2",
                text="We're going out for food this weekend. You in?",
                text_cn="我们这周末出去觅食,你来吗?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="Nice to meet you! I'm Li Ming. I like hiking. Any good trails around here?",
                text_cn="很高兴认识你!我叫李明。我喜欢徒步,这附近有不错的步道吗?",
            ),
            SuggestionLine(
                text="Sounds fun! What time and where do we meet?",
                text_cn="听起来不错!几点、在哪儿集合?",
            ),
        ),
        beats=(
            "打招呼、自我介绍:名字、从哪儿来",
            "聊一个话题:爱好、周末、或本地好吃的",
            "接住对方的话,再反问一句",
            "留个由头:约下次、交换联系方式",
        ),
    ),
    DialogueScene(
        id="team_meeting",
        title="团队会议",
        description="开小组会:同步进度、回答追问、接住提议、确认下一步分工。",
        title_en="A Team Meeting",
        description_en="Join a team meeting: give your update, answer questions, react to ideas, and confirm next steps.",
        roles=(
            SceneRole(
                role_id="r1",
                name="组长 Dan",
                name_en="Team Lead Dan",
                voice="Dean",
                persona="the team lead who runs the meeting, asks for updates, and assigns next steps",
                persona_cn="主持会议的组长,要进展、派下一步活",
            ),
            SceneRole(
                role_id="r2",
                name="同事 Emma",
                name_en="Teammate Emma",
                voice="Chloe",
                persona="an energetic teammate who shares ideas and asks the learner's opinion",
                persona_cn="活跃的同事,分享想法、会问学员意见",
            ),
            SceneRole(
                role_id="r3",
                name="同事 Olivia",
                name_en="Teammate Olivia",
                voice="Mia",
                persona="a quiet teammate who takes the notes and reads them back at the end",
                persona_cn="安静的同事,做会议记录、结尾复述一遍",
            ),
        ),
        user_role="会上要发言的组员",
        user_role_en="a team member speaking up in the meeting",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Let's start. Quick updates first, one or two lines each.",
                text_cn="开始吧。先快速同步,每人一两句话。",
            ),
            OpeningLine(
                role_id="r2",
                text="I finished the login page yesterday. How's your part going?",
                text_cn="我昨天做完了登录页。你那部分怎么样了?",
            ),
            OpeningLine(
                role_id="r3",
                text="I'm taking notes today. Tell me if I miss anything.",
                text_cn="今天我来记录。我漏了就告诉我。",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="I'm almost done. I just need one more day to test it.",
                text_cn="我快做完了,还需要一天测试。",
            ),
            SuggestionLine(
                text="Sorry, could you say that again? Which day is the deadline?",
                text_cn="抱歉,能再说一遍吗?截止日期是星期几?",
            ),
        ),
        beats=(
            "做一小段进度同步:做完什么、卡在哪",
            "回答组长追问:需要什么、什么时候能好",
            "接住同事提议:同意,或说出不同意见",
            "确认分工:谁做什么、哪天交",
        ),
    ),
    DialogueScene(
        id="work_report",
        title="工作汇报",
        description="向经理汇报工作:说进展、报数字、回答追问、定下一步。",
        title_en="Reporting to Your Manager",
        description_en="Report your work to the manager: share progress, give the numbers, answer follow-ups, agree on next steps.",
        roles=(
            SceneRole(
                role_id="r1",
                name="经理 Anna",
                name_en="Manager Anna",
                voice="Mia",
                persona="a busy manager who listens to the report, asks about numbers and risks, and sets the next target",
                persona_cn="干练的经理,听汇报、追问数字和风险、定下一步",
            ),
            SceneRole(
                role_id="r2",
                name="同事 Ben",
                name_en="Teammate Ben",
                voice="Dean",
                persona="a teammate whose own plan depends on the project and asks how it changes things",
                persona_cn="排期依赖该项目的同事,追问对自己的影响",
            ),
        ),
        user_role="向经理做汇报的下属",
        user_role_en="an employee giving a work report",
        opening_lines=(
            OpeningLine(
                role_id="r1",
                text="Thanks for preparing this. Give me the short version first.",
                text_cn="谢谢你的准备。先说简短版。",
            ),
            OpeningLine(
                role_id="r2",
                text="Quick question, will this change what I do next week?",
                text_cn="问一下,这会改变我下周的安排吗?",
            ),
        ),
        suggestion_lines=(
            SuggestionLine(
                text="We're about eighty percent done. We're two days late because of the supplier.",
                text_cn="我们完成了大概八成。因为供应商,晚了两天。",
            ),
            SuggestionLine(
                text="I need one more designer, or we can cut one feature.",
                text_cn="我还需要一名设计师,不然就砍掉一个功能。",
            ),
        ),
        beats=(
            "开场一句说清进展:完成多少、整体顺不顺",
            "报数字:花了多少、晚没晚、原因是什么",
            "回答追问:风险在哪、要什么资源",
            "收尾定下一步:改什么、什么时候再汇报",
        ),
    ),
)


def list_scenes() -> list[DialogueScene]:
    """Return every scene the client's chat list can show."""
    return list(_DEFAULT_SCENES)


def resolve_scene(scene_id: str) -> DialogueScene | None:
    """按 id 精确命中目录; 未知名返回 ``None`` —— **没有**"静默当第一个场景"的兜底。

    旧版 ``get_scene`` 对任何拼错的 id 回落到 ``business_meeting`` (顺序是"目录第一
    条"), 于是乱拼 id 的学员被教成"商务会议"而界面毫无提示: 调用方拿到 ``None`` 一律
    404 ``SCENE_NOT_FOUND`` (自定义 ``custom_<id>`` 的归属判定在 ``api/v1/dialogue.py``,
    不在此模块 —— 这里保持纯静态素材, 不知道 DB)。
    """
    for scene in _DEFAULT_SCENES:
        if scene.id == scene_id:
            return scene
    return None
