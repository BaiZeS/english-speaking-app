package com.app.english.domain.model

/**
 * 情景课全流程(P6)的领域模型: 课程内容 / 会话快照 / 实战轮 / 复盘报告。
 * 全部由 `data/remote/SessionMappers.kt` 从 DTO 映射, 界面层不接触裸 JSON 字段。
 */

/** 一门情景课的完整内容(`GET /scenes/{id}` 的 `SceneCourse`)。 */
data class SceneCourseDetail(
    val id: String,
    val source: String = "curated",
    val category: String = "",
    val title: String = "",
    val subtitleEn: String = "",
    val goalText: String = "",
    val level: String = "A2",
    val estMinutes: Int = 8,
    val briefCn: String = "",
    val vocab: List<VocabCard> = emptyList(),
    val briefing: List<FoundationStepSpec> = emptyList(),
    val mission: MissionSpecDetail = MissionSpecDetail(),
    val skills: List<String> = emptyList()
) {
    val isGenerated: Boolean get() = source == "generated"
    val requiredTaskCount: Int get() = mission.tasks.count { it.required }
}

/** 词汇卡: 点击播单词或例句。 */
data class VocabCard(
    val word: String,
    val ipa: String,
    val meaningCn: String,
    val exampleEn: String
)

/** 打基础一步的题目内容(题型决定卡片样式)。 */
data class FoundationStepSpec(
    val id: String,
    // read_along | retell | translate | make_sentence
    val type: String,
    val cnPrompt: String,
    val refText: String,
    val translationCn: String,
    val referenceAnswer: String,
    val targetWord: String,
    val acceptNotes: String
)

data class MissionSpecDetail(
    val personaCn: String = "",
    val userRoleCn: String = "",
    val contextCn: String = "",
    val openingA: String = "",
    val openingACn: String = "",
    val exchanges: List<ScriptExchange> = emptyList(),
    val tasks: List<MissionTaskSpec> = emptyList(),
    val maxTurns: Int = 12
)

/** 参考剧本一对往来(a=AI, b=学员), 复盘页参考剧本直接播。 */
data class ScriptExchange(val a: String, val b: String, val aCn: String, val bCn: String)

data class MissionTaskSpec(
    val id: String,
    val descCn: String,
    val hintEn: String,
    val hintCn: String,
    val required: Boolean
)

/** 一次 drill 尝试的评分结果。 */
data class DrillGradeResult(
    val stepId: String,
    val stepType: String,
    val score: Double,
    val passed: Boolean,
    val passScore: Double,
    val feedbackCn: String,
    val pronunciation: Double? = null,
    val fluency: Double? = null,
    val completeness: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val transcript: String? = null,
    val wordDetails: List<WordScore> = emptyList(),
    val keyPointsHit: List<String> = emptyList(),
    val mistakes: List<DrillMistake> = emptyList(),
    // xunfei | llm | stub | skip —— UI 据此打"非真实评测"警示。
    val source: String = "stub",
    val llmSource: String? = null
) {
    /** 没有真实评分证据(xunfei/llm 之外)时界面要挂警示标。 */
    val isRealEvidence: Boolean get() = source == "xunfei" || source == "llm"

    /**
     * `/skip-step` 复用 `/step` 的响应形状, 塞进来的是 `score=0` + `passed=true` +
     * `llm_source="skip"`(见 `course_sessions._skipped_grade`)。那个 0 不是分数, 是占位
     * —— 照原样画就会得到一枚刺眼的「0 分」旁边写着「过关」。界面据此改说人话。
     */
    val isSkipped: Boolean get() = source == "skip" || llmSource == "skip"
}

data class DrillMistake(
    val sourceCn: String,
    val said: String,
    val better: String,
    val explanationCn: String
)

/** 打基础清单里一步的当前位置(渲染进度点 + 重做提示)。 */
data class BriefingStepState(
    val id: String,
    val index: Int,
    val type: String,
    val status: String,
    val attempts: Int = 0,
    val bestScore: Double? = null,
    val lastScore: Double? = null,
    val lastSource: String? = null,
    /**
     * 服务端为这一步**单独留档**的完整评分(`step.last_grade`)。存在的理由就是让
     * 客户端不必重算也能把反馈原样摆回来 —— 以前在映射层被丢掉, 于是重进/崩溃恢复后
     * 每一步的反馈全部消失, 只剩一个分数。
     */
    val lastGrade: DrillGradeResult? = null
)

data class BriefingProgress(
    val total: Int = 0,
    val done: Int = 0,
    val passed: Int = 0,
    val skipped: Int = 0,
    val skipsUsed: Int = 0,
    val skipLimit: Int = 2,
    val skipsRemaining: Int = 0,
    val nextStepId: String? = null,
    val unlockedMission: Boolean = false,
    val steps: List<BriefingStepState> = emptyList()
)

/** 任务清单 chip(实战 HUD 顶部横滑)。 */
data class TaskChip(
    val id: String,
    val descCn: String,
    val hintEn: String,
    val required: Boolean,
    val done: Boolean,
    val evidence: String
)

/** 「原句 vs 更好说法」—— 润色气泡 / 复盘对照 / 表达库卡片共用。 */
data class PolishSuggestion(val original: String, val polished: String, val explanationCn: String)

/** 实战对话一轮完成后加进消息列表的条目。 */
data class MissionTurn(
    val turnIndex: Int,
    val transcript: String,
    val reply: String,
    val suggestion: String,
    val polish: PolishSuggestion? = null,
    val newlyDone: List<NewlyDoneTask> = emptyList(),
    val costsScore: Boolean = false,
    /**
     * 本轮的发音/语法证据(键与 [DrillGradeResult] 的五维同名, null = 这一维没测到)。
     * 实战用的是语音轮, 讯飞 ISE 的分本来就在响应里 (`sub_scores`/`word_details`),
     * 以前映射层直接丢掉 -> 实战语音轮和打基础一样, 说完听不到任何发音反馈。
     * 逐词分只用来提炼"哪几个词没读准", 不在气泡里铺开整排芯片(一屏 6-12 轮会把台词
     * 本身盖掉)。
     */
    val subScores: Map<String, Double?> = emptyMap(),
    val wordDetails: List<WordScore> = emptyList(),
    val speechRateWpm: Double? = null
)

data class NewlyDoneTask(val id: String, val evidence: String)

/** `GET /sessions/{id}` 恢复快照(同一形状喂给详情/打基础/实战/复盘四页)。 */
data class SessionSnapshot(
    val sessionId: String,
    val sceneId: String,
    val stage: String,
    val status: String,
    val revision: Int,
    val briefing: BriefingProgress = BriefingProgress(),
    // 恢复实战页: 历史轮 + 任务清单 + 开场白; 首轮之前为 null。
    val mission: MissionRecovery? = null,
    val review: ReviewReportData? = null,
    /**
     * 总评文案的作业状态(`generating` / `ready` / `failed`; 未收工为 null)。
     * §P6 的轮询键 —— 报告的**数值**不依赖它: 收工那次 commit 就已经把数值骨架写进
     * [review] 了, 这个键只说"那两句 AI 文案补没补"。取值与解读集中在
     * [com.app.english.ui.scenes.ReviewPollingPolicy](脏值/缺字段按"不可知, 别再等"
     * 处理, 绝不让复盘页卡在转圈上 —— 那正是本次要修的 bug 的形状)。
     */
    val reviewStatus: String? = null,
    val course: SceneCourseDetail? = null
)

data class MissionRecovery(
    val openingA: String,
    val openingACn: String,
    val turns: List<MissionTurnLog>,
    val tasks: List<TaskChip>,
    val turnCount: Int,
    val maxTurns: Int
)

/** 恢复页面时按快照重绘的历史轮(不重复打接口)。 */
data class MissionTurnLog(
    val turnIndex: Int,
    val transcript: String,
    val reply: String,
    val polish: PolishSuggestion?,
    val costsScore: Boolean
)

/** 实战一轮的完整响应(状态机推进 + 收工判定)。 */
data class MissionTurnResult(
    val turn: MissionTurn,
    val checklist: List<TaskChip>,
    val cleared: Boolean,
    val turnCount: Int,
    val maxTurns: Int,
    val autoFinished: Boolean,
    val finished: Boolean,
    val costsScore: Boolean,
    // llm | heuristic —— heuristic 时界面提示"本轮为离线降级判定"。
    val source: String,
    val llmSource: String?,
    val review: ReviewReportData?,
    /**
     * 仅 `autoFinished` 时有值(§P6): 到轮次上限被服务端**自动收工**, 数值骨架已随本次
     * 响应落库, AI 文案交给后台作业。以前这条路径也在同一请求里同步写文案, 于是"一天
     * 练到自然结束"必然撞上手机 30s 读超时(比人工「收工」更高频)。现在它和人工收工一样:
     * [review] 一到手就跳复盘页, 由复盘页轮询这个状态键。
     */
    val reviewStatus: String? = null
)

/**
 * 「收工」的 202 回执(§P6)。
 *
 * 只有"服务端已经把这局关掉、文案作业已排上"这一件事, 报告本体**不在**这里 ——
 * 那正是收工从 ~68s(最坏 ~125s)掉回亚秒级、不再撞 30s 读超时的原因。
 * 界面拿到它就立刻跳复盘页, 由复盘页轮询 [SessionSnapshot.reviewStatus]。
 */
data class MissionFinishAck(val sessionId: String, val revision: Int, val reviewStatus: String?)

data class HintData(
    val taskId: String?,
    val descCn: String,
    val hintEn: String,
    val scriptLine: String,
    val noteCn: String
)

/** 复盘报告(`ReviewReport`)。 */
data class ReviewReportData(
    val sessionId: String,
    val sceneId: String,
    val title: String,
    val cleared: Boolean,
    val autoFinished: Boolean,
    val turnCount: Int,
    val maxTurns: Int,
    val overall: Double?,
    val dims: Map<String, Double?>,
    val pronunciationSubs: Map<String, Double?>,
    /**
     * 无可信评分证据时(`overall` 为 null)服务端替界面说的那句中文(§P6 次因)。
     * 存在的理由: 一个光秃秃的「—」读起来像"你考了 0 分", 而实情是这一场**没有可信
     * 证据可打分**(讯飞/LLM 未配置或全部降级)。这两种含义对学员完全不同, 不能让 UI 猜。
     */
    val evidenceNoteCn: String = "",
    val highlights: List<String>,
    val improvements: List<String>,
    val checklist: List<TaskChip>,
    val transcriptPairs: List<PolishSuggestion>,
    val newTokens: List<String>,
    val abilityDelta: Map<String, Double?>,
    val hintsUsed: Int,
    // llm = 模型文案; heuristic = 离线降级文案(界面挂警示)。
    // 注意 §P6: `heuristic` **不代表**"还在生成中" —— 文案作业跑完但 LLM 挂着时,
    // `review_status == "ready"` + `source == "heuristic"` 就是最终诚实答案。
    // 判断要不要继续等只读 reviewStatus。
    val source: String,
    val llmSource: String?
) {
    /** 维度条渲染顺序(缺失/无证据的维度显示「本轮无证据」)。 */
    val dimOrder: List<String>
        get() = listOf("pronunciation", "grammar", "vocabulary", "fluency")
}

/** 首页「继续学习」/详情页「查看上次复盘」的目标(会话摘要, 同一形状两种用法)。 */
data class ContinueSession(
    val sessionId: String,
    val sceneId: String,
    val title: String,
    val level: String,
    val stage: String,
    val doneSteps: Int,
    val totalSteps: Int,
    val unlockedMission: Boolean,
    /**
     * `active` / `completed` / `abandoned`。§P6 加它只为一件事: 回看入口**只**认
     * `completed`。列表请求本身带 `status` 过滤, 但不能假定过滤一定生效(旧服务端、
     * 代理、以后有人改调用方), 而把一场还在练的会话链到复盘页 = 学员点进一个空壳。
     */
    val status: String = ""
)

/** 生成任务的客户端视图(轮询进度页)。 */
data class GenerationJob(
    val jobId: String,
    val status: String,
    val progress: Double,
    val stageText: String,
    val sceneId: String?,
    val error: String?
) {
    val isRunning: Boolean get() = status == "running"
    val isReady: Boolean get() = status == "ready"
    val isFailed: Boolean get() = status == "failed"
}

/** 表达库条目(词汇 Tab / 润色收藏)。 */
data class ExpressionEntry(
    val id: String,
    val polished: String,
    val original: String,
    val explanationCn: String,
    val sourceLabel: String,
    val sceneId: String,
    val createdAt: String
)
