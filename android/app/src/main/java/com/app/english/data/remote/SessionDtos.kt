package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * 通关会话状态机(计划 §5.3)的全套载荷, 形状一一对应
 * `backend/app/api/v1/course_sessions.py` 的 pydantic 模型(2026-09-05 本机起服
 * 实测样本存 `.mimocode/tasks/T7/zcode-report.md`)。可选字段全部带默认值,
 * 后端加减字段不炸客户端。
 */
@Serializable
data class CreateSessionRequestDto(
    @SerialName("device_id") val deviceId: String,
    val kind: String = "scene_course",
    @SerialName("scene_id") val sceneId: String
)

/** 打基础清单里一步的当前位置与结果(`StepProgress`)。 */
@Serializable
data class StepProgressDto(
    val id: String,
    val index: Int = 0,
    val type: String = "",
    val status: String = "pending",
    val attempts: Int = 0,
    @SerialName("best_score") val bestScore: Double? = null,
    @SerialName("last_score") val lastScore: Double? = null,
    @SerialName("last_source") val lastSource: String? = null,
    @SerialName("last_grade") val lastGrade: DrillGradeDto? = null
)

/** 打基础阶段的进度汇总(`BriefingProgress`)。 */
@Serializable
data class BriefingProgressDto(
    val total: Int = 0,
    val done: Int = 0,
    val passed: Int = 0,
    val skipped: Int = 0,
    @SerialName("skips_used") val skipsUsed: Int = 0,
    @SerialName("skip_limit") val skipLimit: Int = 2,
    @SerialName("skips_remaining") val skipsRemaining: Int = 0,
    @SerialName("next_step_id") val nextStepId: String? = null,
    @SerialName("unlocked_mission") val unlockedMission: Boolean = false,
    val steps: List<StepProgressDto> = emptyList()
)

/**
 * `POST /sessions` 与 `GET /sessions/{id}` 的同一形状(`SessionView`)。
 * `mission` 是服务端状态机的实战分区快照; `review` 只在收工后出现。
 */
@Serializable
data class SessionViewDto(
    @SerialName("session_id") val sessionId: String,
    val kind: String = "scene_course",
    @SerialName("scene_id") val sceneId: String = "",
    val stage: String = "briefing",
    val status: String = "active",
    val revision: Int = 0,
    @SerialName("created_at") val createdAt: String = "",
    @SerialName("last_active_at") val lastActiveAt: String = "",
    val briefing: BriefingProgressDto = BriefingProgressDto(),
    val mission: MissionSnapshotDto? = null,
    val review: ReviewReportDto? = null,
    val course: SceneCourseDto? = null
)

/** `GET /sessions` 列表项(`SessionSummary`, 首页「继续学习」)。 */
@Serializable
data class SessionSummaryDto(
    @SerialName("session_id") val sessionId: String,
    val kind: String = "scene_course",
    @SerialName("scene_id") val sceneId: String = "",
    val stage: String = "",
    val status: String = "",
    val title: String = "",
    val level: String = "",
    @SerialName("done_steps") val doneSteps: Int = 0,
    @SerialName("total_steps") val totalSteps: Int = 0,
    @SerialName("unlocked_mission") val unlockedMission: Boolean = false,
    @SerialName("last_active_at") val lastActiveAt: String = ""
)

@Serializable
data class StepAttemptRequestDto(
    @SerialName("device_id") val deviceId: String,
    @SerialName("step_id") val stepId: String,
    val text: String? = null,
    // pydantic bytes 字段: JSON 里就是 base64 字符串(与 ScoreRequest.audio 同口径)。
    @SerialName("audio_b64") val audioB64: String? = null
)

/** 一次 drill 尝试的评分(`DrillGrade`): 维度分 null = 该维度本轮无证据。 */
@Serializable
data class DrillGradeDto(
    @SerialName("step_id") val stepId: String = "",
    @SerialName("step_type") val stepType: String = "",
    val score: Double = 0.0,
    val passed: Boolean = false,
    @SerialName("pass_score") val passScore: Double = 60.0,
    @SerialName("feedback_cn") val feedbackCn: String = "",
    val pronunciation: Double? = null,
    val fluency: Double? = null,
    val completeness: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val transcript: String? = null,
    @SerialName("word_details") val wordDetails: List<WordScoreDto> = emptyList(),
    @SerialName("key_points_hit") val keyPointsHit: List<String> = emptyList(),
    val mistakes: List<DrillMistakeDto> = emptyList(),
    @SerialName("speech_rate_wpm") val speechRateWpm: Double? = null,
    @SerialName("ise_ref_mode") val iseRefMode: String? = null,
    val source: String = "stub",
    @SerialName("llm_source") val llmSource: String? = null
)

/** 翻译/造句的误译清单条目(`DrillMistake`)。 */
@Serializable
data class DrillMistakeDto(
    @SerialName("source_cn") val sourceCn: String = "",
    val said: String = "",
    val better: String = "",
    @SerialName("explanation_cn") val explanationCn: String = ""
)

/** `POST /sessions/{id}/step` 与 `/skip-step` 的返回(`StepAttemptResponse`)。 */
@Serializable
data class StepAttemptResponseDto(
    @SerialName("session_id") val sessionId: String,
    val revision: Int = 0,
    val stage: String = "briefing",
    val status: String = "active",
    val grade: DrillGradeDto = DrillGradeDto(),
    val briefing: BriefingProgressDto = BriefingProgressDto(),
    @SerialName("unlocked_mission") val unlockedMission: Boolean = false,
    @SerialName("ability_events") val abilityEvents: List<AbilityEvidenceDto> = emptyList()
)

@Serializable
data class AbilityEvidenceDto(
    val dimension: String = "",
    val score: Double? = null,
    val source: String = "stub",
    val weight: Double = 0.0
)

// ====== 实战对话(mission) ======

@Serializable
data class MissionTurnRequestDto(
    @SerialName("device_id") val deviceId: String,
    val text: String? = null,
    @SerialName("audio_b64") val audioB64: String? = null
)

/** 「原句 vs 更好说法」对照(`Polish`), mission / 自由对话 / 独立润色共用。 */
@Serializable
data class PolishDto(
    val original: String = "",
    val polished: String = "",
    @SerialName("explanation_cn") val explanationCn: String = ""
)

/** 任务清单视图(`MissionTaskView`)。 */
@Serializable
data class MissionTaskViewDto(
    val id: String,
    @SerialName("desc_cn") val descCn: String = "",
    @SerialName("hint_en") val hintEn: String = "",
    val required: Boolean = true,
    val done: Boolean = false,
    val evidence: String = "",
    @SerialName("done_at_turn") val doneAtTurn: Int? = null
)

@Serializable
data class NewlyDoneTaskDto(val id: String = "", val evidence: String = "")

/** `POST /sessions/{id}/mission` 一轮的返回(`MissionTurnResponse`)。 */
@Serializable
data class MissionTurnResponseDto(
    @SerialName("session_id") val sessionId: String,
    val revision: Int = 0,
    val stage: String = "mission",
    val status: String = "active",
    @SerialName("turn_index") val turnIndex: Int = 0,
    val transcript: String = "",
    val reply: String = "",
    val suggestion: String = "",
    val polish: PolishDto? = null,
    @SerialName("sub_scores") val subScores: Map<String, Double?> = emptyMap(),
    @SerialName("word_details") val wordDetails: List<WordScoreDto> = emptyList(),
    @SerialName("speech_rate_wpm") val speechRateWpm: Double? = null,
    @SerialName("newly_done") val newlyDone: List<NewlyDoneTaskDto> = emptyList(),
    val checklist: List<MissionTaskViewDto> = emptyList(),
    val cleared: Boolean = false,
    @SerialName("turn_count") val turnCount: Int = 0,
    @SerialName("max_turns") val maxTurns: Int = 0,
    @SerialName("auto_finished") val autoFinished: Boolean = false,
    val finished: Boolean = false,
    @SerialName("ability_events") val abilityEvents: List<AbilityEvidenceDto> = emptyList(),
    val source: String = "heuristic",
    @SerialName("llm_source") val llmSource: String? = null,
    @SerialName("costs_score") val costsScore: Boolean = false,
    val review: ReviewReportDto? = null
)

/** `GET /sessions/{id}` 恢复快照里 mission 分区实际被消费的字段子集。 */
@Serializable
data class MissionSnapshotDto(
    val opening: MissionOpeningDto? = null,
    val turns: List<MissionTurnLogDto> = emptyList(),
    val tasks: List<MissionTaskViewDto> = emptyList(),
    @SerialName("turn_count") val turnCount: Int = 0,
    @SerialName("max_turns") val maxTurns: Int = 0,
    val cleared: Boolean = false,
    val finished: Boolean = false,
    @SerialName("hints_used") val hintsUsed: Int = 0
)

@Serializable
data class MissionOpeningDto(val a: String = "", @SerialName("a_cn") val aCn: String = "")

/** 历史轮次日志(doc["mission"]["turns"] 条目的渲染字段子集)。 */
@Serializable
data class MissionTurnLogDto(
    val index: Int = 0,
    @SerialName("user_text") val userText: String = "",
    val reply: String = "",
    val suggestion: String = "",
    val polish: PolishDto? = null,
    @SerialName("costs_score") val costsScore: Boolean = false,
    val source: String = "heuristic"
)

@Serializable
data class MissionHintPayloadDto(
    @SerialName("task_id") val taskId: String? = null,
    @SerialName("desc_cn") val descCn: String = "",
    @SerialName("hint_en") val hintEn: String = "",
    @SerialName("script_line") val scriptLine: String = "",
    @SerialName("note_cn") val noteCn: String = ""
)

@Serializable
data class HintResponseDto(
    @SerialName("session_id") val sessionId: String,
    val revision: Int = 0,
    val stage: String = "",
    val status: String = "",
    val hint: MissionHintPayloadDto = MissionHintPayloadDto(),
    @SerialName("costs_score") val costsScore: Boolean = true,
    @SerialName("hints_used") val hintsUsed: Int = 0
)

@Serializable
data class FinishMissionResponseDto(
    @SerialName("session_id") val sessionId: String,
    val revision: Int = 0,
    val stage: String = "review",
    val status: String = "completed",
    val report: ReviewReportDto = ReviewReportDto("", "")
)

// ====== 复盘报告(ReviewReport, §5.3) ======

/** 「原话 vs 更好说法」对照行(`TranscriptPair`)。 */
@Serializable
data class TranscriptPairDto(
    val original: String = "",
    val polished: String = "",
    @SerialName("explanation_cn") val explanationCn: String = "",
    val source: String = "mission"
)

@Serializable
data class ReviewReportDto(
    @SerialName("session_id") val sessionId: String,
    @SerialName("scene_id") val sceneId: String,
    val title: String = "",
    val cleared: Boolean = false,
    @SerialName("auto_finished") val autoFinished: Boolean = false,
    @SerialName("turn_count") val turnCount: Int = 0,
    @SerialName("max_turns") val maxTurns: Int = 0,
    val overall: Double? = null,
    val dims: Map<String, Double?> = emptyMap(),
    @SerialName("pronunciation_subs") val pronunciationSubs: Map<String, Double?> = emptyMap(),
    val highlights: List<String> = emptyList(),
    val improvements: List<String> = emptyList(),
    val checklist: List<MissionTaskViewDto> = emptyList(),
    @SerialName("transcript_pairs") val transcriptPairs: List<TranscriptPairDto> = emptyList(),
    @SerialName("new_tokens") val newTokens: List<String> = emptyList(),
    @SerialName("ability_delta") val abilityDelta: Map<String, Double?> = emptyMap(),
    @SerialName("hints_used") val hintsUsed: Int = 0,
    val source: String = "heuristic",
    @SerialName("llm_source") val llmSource: String? = null
)
