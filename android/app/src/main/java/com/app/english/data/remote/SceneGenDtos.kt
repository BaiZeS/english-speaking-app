package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * `GET /scenes/{id}` 的整课内容, 形状对应 `backend/app/models/course.py::SceneCourse`。
 * 会话端点把整份课程快照在 `SessionView.course` 里一并回, 复用同一套 DTO。
 */
@Serializable
data class SceneCourseDto(
    @SerialName("schema_version") val schemaVersion: Int = 1,
    val id: String,
    val source: String = "curated",
    val category: String = "",
    val title: String = "",
    @SerialName("subtitle_en") val subtitleEn: String = "",
    @SerialName("goal_text") val goalText: String = "",
    val level: String = "A2",
    @SerialName("est_minutes") val estMinutes: Int = 8,
    @SerialName("brief_cn") val briefCn: String = "",
    val vocab: List<VocabItemDto> = emptyList(),
    val briefing: List<FoundationStepDto> = emptyList(),
    val mission: MissionSpecDto = MissionSpecDto(),
    val skills: List<String> = emptyList()
)

/** 词汇卡(课程详情横向滑动卡)。 */
@Serializable
data class VocabItemDto(
    val word: String = "",
    val ipa: String = "",
    @SerialName("meaning_cn") val meaningCn: String = "",
    @SerialName("example_en") val exampleEn: String = ""
)

/** 打基础一步; 字段按题型可选, 契约校验在后端。 */
@Serializable
data class FoundationStepDto(
    val id: String = "",
    val type: String = "",
    @SerialName("cn_prompt") val cnPrompt: String = "",
    @SerialName("ref_text") val refText: String = "",
    @SerialName("translation_cn") val translationCn: String = "",
    @SerialName("reference_answer") val referenceAnswer: String = "",
    @SerialName("target_word") val targetWord: String = "",
    @SerialName("accept_notes") val acceptNotes: String = ""
)

@Serializable
data class MissionSpecDto(
    @SerialName("persona_cn") val personaCn: String = "",
    @SerialName("user_role_cn") val userRoleCn: String = "",
    @SerialName("context_cn") val contextCn: String = "",
    @SerialName("opening_a") val openingA: String = "",
    @SerialName("opening_a_cn") val openingACn: String = "",
    val exchanges: List<DialogueExchangeDto> = emptyList(),
    val tasks: List<MissionTaskSpecDto> = emptyList(),
    @SerialName("max_turns") val maxTurns: Int = 12
)

/** 参考剧本的一对往来: a = AI 台词, b = 学员台词。 */
@Serializable
data class DialogueExchangeDto(
    val a: String = "",
    val b: String = "",
    @SerialName("a_cn") val aCn: String = "",
    @SerialName("b_cn") val bCn: String = ""
)

@Serializable
data class MissionTaskSpecDto(
    val id: String = "",
    @SerialName("desc_cn") val descCn: String = "",
    @SerialName("hint_en") val hintEn: String = "",
    @SerialName("hint_cn") val hintCn: String = "",
    val required: Boolean = true
)

// ====== 课程生成(计划 §5.3 生成任务) ======

@Serializable
data class GenerateSceneRequestDto(
    @SerialName("device_id") val deviceId: String,
    @SerialName("goal_text") val goalText: String,
    val category: String? = null,
    val level: String? = null
)

/** 202 载荷: 轮询地址直接给全。 */
@Serializable
data class GenerateAcceptedDto(
    @SerialName("job_id") val jobId: String,
    @SerialName("polling_url") val pollingUrl: String = ""
)

/** `GET /scenes/jobs/{job_id}` 轮询载荷; 终态 ready 带 scene_id, failed 带 error。 */
@Serializable
data class GenerationJobDto(
    @SerialName("job_id") val jobId: String,
    val status: String = "running",
    val progress: Double = 0.0,
    @SerialName("stage_text") val stageText: String = "",
    @SerialName("scene_id") val sceneId: String? = null,
    val error: String? = null
)

// ====== 通关进度(计划 §5.2 M3 course_progress) ======

@Serializable
data class CourseProgressItemDto(
    @SerialName("scene_id") val sceneId: String,
    val attempts: Int = 0,
    val cleared: Boolean = false,
    @SerialName("best_total") val bestTotal: Double = 0.0,
    @SerialName("last_stage") val lastStage: String = "",
    @SerialName("last_session_id") val lastSessionId: String = "",
    @SerialName("estimated_seconds") val estimatedSeconds: Double = 0.0
)

@Serializable
data class CourseProgressPageDto(
    val total: Int = 0,
    val progress: List<CourseProgressItemDto> = emptyList()
)
