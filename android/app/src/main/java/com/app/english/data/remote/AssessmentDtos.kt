package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * CEFR 测评 + 能力画像(计划 §5.3/§5.6)的载荷, 形状一一对应
 * `backend/app/api/v1/assessment.py` 与 `ability.py` 的 pydantic 模型。
 * 可选字段全部带默认值 —— 后端加减字段不炸客户端。
 */

/** `GET /assessment` 与 `POST /assessment/start` 共用的题目摘要(`QuestionSummary`)。 */
@Serializable
data class AssessmentQuestionDto(
    val id: String,
    val no: Int,
    val type: String = "",
    @SerialName("cefr_anchor") val cefrAnchor: String = "",
    @SerialName("cn_prompt") val cnPrompt: String = "",
    @SerialName("display_text") val displayText: String = "",
    @SerialName("translation_cn") val translationCn: String = "",
    val seconds: Int = 30
)

@Serializable
data class AssessmentBankDto(
    val total: Int = 0,
    val questions: List<AssessmentQuestionDto> = emptyList()
)

/** `POST /assessment/start` 的载荷(`StartResponse`)。 */
@Serializable
data class AssessmentStartRequestDto(@SerialName("device_id") val deviceId: String)

@Serializable
data class AssessmentStartResponseDto(
    @SerialName("attempt_id") val attemptId: String,
    val total: Int = 0,
    val questions: List<AssessmentQuestionDto> = emptyList()
)

/** `POST /assessment/{attempt_id}/answer`; 文本与音频二选一(`AnswerRequest`)。 */
@Serializable
data class AssessmentAnswerRequestDto(
    @SerialName("device_id") val deviceId: String,
    @SerialName("question_no") val questionNo: Int,
    val text: String? = null,
    // pydantic bytes 字段: JSON 里就是 base64 字符串(与 ScoreRequest.audio 同口径)。
    @SerialName("audio_b64") val audioB64: String? = null
)

@Serializable
data class AssessmentAnswerResponseDto(
    @SerialName("attempt_id") val attemptId: String,
    @SerialName("question_no") val questionNo: Int,
    @SerialName("answers_count") val answersCount: Int = 0,
    val total: Int = 0,
    val transcript: String = ""
)

@Serializable
data class AssessmentCompleteRequestDto(@SerialName("device_id") val deviceId: String)

/** 测评雷达的一轴(`RadarAxis`); score=null = 该维没有可信证据。 */
@Serializable
data class AssessmentRadarAxisDto(
    val dimension: String,
    val score: Double? = null,
    val max: Double = 100.0,
    val n: Int = 0
)

/**
 * `POST /assessment/{attempt_id}/complete` 的载荷(`CompleteResponse`)。
 * `source="stub"` = LLM 未配置, cefr/dims 全空 —— 诚实空态, 不冒充定级。
 */
@Serializable
data class AssessmentCompleteResponseDto(
    @SerialName("attempt_id") val attemptId: String,
    val status: String = "completed",
    val cefr: String? = null,
    val dims: Map<String, Double?> = emptyMap(),
    val radar: List<AssessmentRadarAxisDto> = emptyList(),
    @SerialName("rationale_cn") val rationaleCn: String = "",
    @SerialName("pronunciation_source") val pronunciationSource: String? = null,
    val source: String = "stub",
    @SerialName("llm_source") val llmSource: String? = null,
    @SerialName("cefr_level") val cefrLevel: String? = null
)

// ====== 能力画像(`GET /ability?device_id=&days=7|30|90`) ======

/** 画像雷达的一轴(`ability.RadarAxis`)。 */
@Serializable
data class AbilityRadarAxisDto(
    val dimension: String,
    val score: Double? = null,
    val max: Double = 100.0,
    val n: Int = 0
)

/** 轨迹逐日点(`TrajectoryPoint`); 维度 null = 当天该维没有计入证据。 */
@Serializable
data class AbilityTrajectoryPointDto(
    val date: String,
    val pronunciation: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val fluency: Double? = null,
    val events: Int = 0
)

@Serializable
data class AbilityResponseDto(
    @SerialName("device_id") val deviceId: String = "",
    @SerialName("user_id") val userId: String? = null,
    @SerialName("user_found") val userFound: Boolean = false,
    val profile: Map<String, Double?> = emptyMap(),
    val n: Map<String, Int> = emptyMap(),
    val radar: List<AbilityRadarAxisDto> = emptyList(),
    @SerialName("cefr_level") val cefrLevel: String? = null,
    @SerialName("assessment_cefr") val assessmentCefr: String? = null,
    @SerialName("band_locked") val bandLocked: Boolean = false,
    @SerialName("derived_level") val derivedLevel: String? = null,
    val days: Int = 30,
    val trajectory: List<AbilityTrajectoryPointDto> = emptyList(),
    @SerialName("real_events") val realEvents: Int = 0,
    @SerialName("updated_at") val updatedAt: String? = null
)

// ====== 独立润色(`POST /polish`, §5.7) ======

@Serializable
data class PolishRequestDto(
    val text: String,
    @SerialName("device_id") val deviceId: String? = null,
    val collect: Boolean = false,
    @SerialName("scene_id") val sceneId: String = ""
)

@Serializable
data class PolishResponseDto(
    val polish: PolishDto? = null,
    val source: String = "stub",
    @SerialName("llm_source") val llmSource: String? = null,
    @SerialName("expression_id") val expressionId: String? = null,
    @SerialName("note_cn") val noteCn: String = ""
)
