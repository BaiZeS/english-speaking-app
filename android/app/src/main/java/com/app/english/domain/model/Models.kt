package com.app.english.domain.model

data class LessonSummary(
    val id: Int,
    val book: String,
    val lessonNo: Int,
    val title: String,
    val roleCount: Int,
    val durationS: Double
)

data class Line(val id: String, val text: String, val translation: String?, val ipa: String?)

data class Role(val name: String, val lines: List<Line>)

data class LessonDetail(
    val id: Int,
    val book: String,
    val lessonNo: Int,
    val title: String,
    val roles: List<Role>
)

data class WordScore(val word: String, val score: Double, val ipa: String?)

data class ScoreResult(
    val total: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    val wordDetails: List<WordScore>,
    val suggestion: String?
)

data class HistoryItem(
    val id: String,
    val lessonId: Int,
    val lineId: String,
    val scoreTotal: Double,
    val scorePronunciation: Double,
    val scoreFluency: Double,
    val scoreCompleteness: Double,
    val createdAt: String
)
