package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class LessonSummaryDto(
    val id: Int,
    val book: String,
    @SerialName("lesson_no") val lessonNo: Int,
    val title: String,
    @SerialName("role_count") val roleCount: Int,
    @SerialName("duration_s") val durationS: Double
)

@Serializable
data class LineDto(
    val id: String,
    val text: String,
    val translation: String? = null,
    val ipa: String? = null
)

@Serializable
data class RoleDto(val name: String, val lines: List<LineDto>)

@Serializable
data class LessonDetailDto(
    val id: Int,
    val book: String,
    @SerialName("lesson_no") val lessonNo: Int,
    val title: String,
    val roles: List<RoleDto>
)

@Serializable
data class TtsResponseDto(
    @SerialName("audio_url") val audioUrl: String,
    @SerialName("duration_ms") val durationMs: Int,
    // "mimo"=真实合成, "stub"=占位假音频 (未配 MIMO_API_KEY). 旧后端无此字段时取默认值.
    val source: String = "stub"
)

@Serializable
data class WordScoreDto(val word: String, val score: Double, val ipa: String? = null)

/**
 * Score request. Backend declares `audio: bytes` which, in a JSON body,
 * Pydantic decodes from a base64-encoded string. We therefore send audio
 * as a base64 string (Base64.NO_WRAP), capped at 10MB decoded.
 *
 * `lessonId`/`lineId` are optional: the word drill submits a bare word with
 * `category = "read_word"` and no lesson context, while line-based practice
 * keeps the existing shape.
 */
@Serializable
data class ScoreRequestDto(
    @SerialName("lesson_id") val lessonId: Int? = null,
    @SerialName("line_id") val lineId: String? = null,
    @SerialName("ref_text") val refText: String,
    val mode: String = "k12",
    val category: String = "read_sentence",
    val audio: String
)

@Serializable
data class ScoreResponseDto(
    val total: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    @SerialName("word_details") val wordDetails: List<WordScoreDto>,
    val suggestion: String? = null,
    // "xunfei"=真实讯飞评测, "stub"=占位假分 (未配凭据/调用失败). 旧后端无此字段时取默认值.
    val source: String = "stub"
)

@Serializable
data class DialogueLineDto(
    val id: String,
    val role: String,
    val text: String,
    val translation: String? = null,
    @SerialName("is_user") val isUser: Boolean = false
)

@Serializable
data class DialogueGenerateRequestDto(
    val scene: String,
    val mode: String = "adult",
    @SerialName("model_id") val modelId: String? = null
)

@Serializable
data class DialogueGenerateResponseDto(
    @SerialName("scene_id") val sceneId: String,
    val status: String,
    val title: String,
    val lines: List<DialogueLineDto>,
    @SerialName("suggested_reply") val suggestedReply: String,
    @SerialName("model_id") val modelId: String? = null
)

@Serializable
data class DialogueMessageDto(val role: String, val text: String)

@Serializable
data class DialogueTurnRequestDto(
    @SerialName("scene_id") val sceneId: String,
    val history: List<DialogueMessageDto>,
    @SerialName("user_audio_b64") val userAudioB64: String = "",
    @SerialName("model_id") val modelId: String? = null
)

@Serializable
data class DialogueTurnResponseDto(
    val status: String,
    @SerialName("reply_text") val replyText: String,
    @SerialName("reply_audio_url") val replyAudioUrl: String? = null,
    @SerialName("suggested_reply") val suggestedReply: String,
    @SerialName("recognized_text") val recognizedText: String? = null,
    @SerialName("model_id") val modelId: String? = null
)

@Serializable
data class HistoryWriteRequestDto(
    @SerialName("device_id") val deviceId: String,
    @SerialName("book") val book: String = "nce1",
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("line_id") val lineId: String,
    @SerialName("audio_path") val audioPath: String,
    @SerialName("score_total") val scoreTotal: Double,
    @SerialName("score_pronunciation") val scorePronunciation: Double,
    @SerialName("score_fluency") val scoreFluency: Double,
    @SerialName("score_completeness") val scoreCompleteness: Double
)

@Serializable
data class LlmModelDto(
    val id: String,
    @SerialName("display_name") val displayName: String,
    val provider: String,
    val description: String = ""
)

@Serializable
data class LlmModelsResponseDto(
    val models: List<LlmModelDto>,
    @SerialName("default_model") val defaultModel: String
)

@Serializable
data class AppVersionResponseDto(
    @SerialName("latest_version") val latestVersion: String,
    @SerialName("min_supported_version") val minSupportedVersion: String,
    @SerialName("apk_url") val apkUrl: String,
    @SerialName("release_notes") val releaseNotes: String = "",
    @SerialName("force_update") val forceUpdate: Boolean = false
)

@Serializable
data class HistoryItemDto(
    val id: String,
    @SerialName("book") val book: String = "nce1",
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("line_id") val lineId: String,
    @SerialName("score_total") val scoreTotal: Double,
    @SerialName("score_pronunciation") val scorePronunciation: Double,
    @SerialName("score_fluency") val scoreFluency: Double,
    @SerialName("score_completeness") val scoreCompleteness: Double,
    @SerialName("created_at") val createdAt: String
)

@Serializable
data class BookDto(
    val id: String,
    @SerialName("display_name") val displayName: String,
    val description: String,
    val level: String,
    @SerialName("lesson_count") val lessonCount: Int
)

@Serializable
data class BooksResponseDto(
    val books: List<BookDto>,
    @SerialName("default_book") val defaultBook: String
)

@Serializable
data class DialogueSceneDto(val id: String, val title: String, val description: String)

@Serializable
data class DialogueScenesResponseDto(
    val scenes: List<DialogueSceneDto>,
    @SerialName("default_scene") val defaultScene: String
)

@Serializable
data class DailyScoreDto(
    val date: String,
    @SerialName("avg_total") val avgTotal: Double,
    @SerialName("avg_pronunciation") val avgPronunciation: Double,
    @SerialName("avg_fluency") val avgFluency: Double,
    @SerialName("avg_completeness") val avgCompleteness: Double,
    val sessions: Int
)

@Serializable
data class StatsResponseDto(
    @SerialName("total_sessions") val totalSessions: Int,
    @SerialName("avg_total") val avgTotal: Double,
    @SerialName("avg_pronunciation") val avgPronunciation: Double,
    @SerialName("avg_fluency") val avgFluency: Double,
    @SerialName("avg_completeness") val avgCompleteness: Double,
    @SerialName("best_total") val bestTotal: Double,
    @SerialName("recent_sessions") val recentSessions: Int,
    @SerialName("streak_days") val streakDays: Int,
    val daily: List<DailyScoreDto>,
    @SerialName("lessons_attempted") val lessonsAttempted: List<Int>,
    @SerialName("weakest_lessons") val weakestLessons: List<WeakestLessonDto> = emptyList()
)

@Serializable
data class LessonProgressDto(
    @SerialName("book") val book: String = "nce1",
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("attempt_count") val attemptCount: Int,
    @SerialName("best_score") val bestScore: Double,
    @SerialName("last_score") val lastScore: Double,
    @SerialName("last_practiced_at") val lastPracticedAt: String? = null
)

@Serializable
data class WeakestLessonDto(
    @SerialName("book") val book: String = "nce1",
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("best_score") val bestScore: Double,
    @SerialName("avg_score") val avgScore: Double,
    val attempts: Int
)

/**
 * `GET /scenes` 载荷(计划 §5.3 目录与画廊)。后端契约:
 * `backend/app/services/scene_store.py::ScenesPage`。
 *
 * 所有可选字段都带默认值 —— 存量后端没有 /scenes 时整段会 404(仓库层报错),
 * 而后端后续加/减字段时客户端不该因此解码失败。
 */
@Serializable
data class ScenesResponseDto(
    val categories: List<SceneCategoryStatDto> = emptyList(),
    val scenes: List<SceneSummaryDto> = emptyList(),
    val total: Int = 0,
    // 计划里提到 default_scene, 当前后端 ScenesPage 尚未返回该键 —— 保持可选。
    @SerialName("default_scene") val defaultScene: String? = null
)

@Serializable
data class SceneCategoryStatDto(
    val id: String,
    @SerialName("label_cn") val labelCn: String = "",
    val count: Int = 0
)

@Serializable
data class SceneSummaryDto(
    val id: String,
    val source: String = "curated",
    val category: String = "",
    val title: String = "",
    @SerialName("subtitle_en") val subtitleEn: String = "",
    val level: String = "",
    @SerialName("est_minutes") val estMinutes: Int = 0,
    @SerialName("brief_cn") val briefCn: String = "",
    val skills: List<String> = emptyList(),
    @SerialName("vocab_count") val vocabCount: Int = 0,
    @SerialName("briefing_count") val briefingCount: Int = 0,
    @SerialName("task_count") val taskCount: Int = 0,
    @SerialName("required_task_count") val requiredTaskCount: Int = 0,
    @SerialName("max_turns") val maxTurns: Int = 0,
    val cleared: Boolean = false,
    @SerialName("best_total") val bestTotal: Double = 0.0,
    val attempts: Int = 0
)
