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
    @SerialName("duration_ms") val durationMs: Int
)

@Serializable
data class WordScoreDto(val word: String, val score: Double, val ipa: String? = null)

/**
 * Score request. Backend declares `audio: bytes` which, in a JSON body,
 * Pydantic decodes from a base64-encoded string. We therefore send audio
 * as a base64 string (Base64.NO_WRAP), capped at 10MB decoded.
 */
@Serializable
data class ScoreRequestDto(
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("line_id") val lineId: String,
    @SerialName("ref_text") val refText: String,
    val mode: String = "k12",
    val audio: String
)

@Serializable
data class ScoreResponseDto(
    val total: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    @SerialName("word_details") val wordDetails: List<WordScoreDto>,
    val suggestion: String? = null
)

@Serializable
data class HistoryWriteRequestDto(
    @SerialName("device_id") val deviceId: String,
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("line_id") val lineId: String,
    @SerialName("audio_path") val audioPath: String,
    @SerialName("score_total") val scoreTotal: Double,
    @SerialName("score_pronunciation") val scorePronunciation: Double,
    @SerialName("score_fluency") val scoreFluency: Double,
    @SerialName("score_completeness") val scoreCompleteness: Double
)

@Serializable
data class HistoryItemDto(
    val id: String,
    @SerialName("lesson_id") val lessonId: Int,
    @SerialName("line_id") val lineId: String,
    @SerialName("score_total") val scoreTotal: Double,
    @SerialName("score_pronunciation") val scorePronunciation: Double,
    @SerialName("score_fluency") val scoreFluency: Double,
    @SerialName("score_completeness") val scoreCompleteness: Double,
    @SerialName("created_at") val createdAt: String
)
