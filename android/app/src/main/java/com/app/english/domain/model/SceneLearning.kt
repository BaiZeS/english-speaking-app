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
    val lastSource: String? = null
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
    val costsScore: Boolean = false
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
    val review: ReviewReportData?
)

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
    val highlights: List<String>,
    val improvements: List<String>,
    val checklist: List<TaskChip>,
    val transcriptPairs: List<PolishSuggestion>,
    val newTokens: List<String>,
    val abilityDelta: Map<String, Double?>,
    val hintsUsed: Int,
    // llm = 模型文案; heuristic = 离线降级文案(界面挂警示)。
    val source: String,
    val llmSource: String?
) {
    /** 维度条渲染顺序(缺失/无证据的维度显示「本轮无证据」)。 */
    val dimOrder: List<String>
        get() = listOf("pronunciation", "grammar", "vocabulary", "fluency")
}

/** 首页「继续学习」目标(最近 active 会话摘要)。 */
data class ContinueSession(
    val sessionId: String,
    val sceneId: String,
    val title: String,
    val level: String,
    val stage: String,
    val doneSteps: Int,
    val totalSteps: Int,
    val unlockedMission: Boolean
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
