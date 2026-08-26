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
    val suggestion: String?,
    // "xunfei"=真实评测, "stub"=占位假分. UI 据此提示用户.
    val source: String = "stub"
) {
    val isStub: Boolean get() = source != "xunfei"
}

data class TtsAudio(
    val audioUrl: String,
    val durationMs: Int,
    // "mimo"=真实合成, "stub"=占位假音频.
    val source: String = "stub"
) {
    val isStub: Boolean get() = source != "mimo"
}

data class HistoryItem(
    val id: String,
    val book: String = "nce1",
    val lessonId: Int,
    val lineId: String,
    val scoreTotal: Double,
    val scorePronunciation: Double,
    val scoreFluency: Double,
    val scoreCompleteness: Double,
    val createdAt: String
)

data class DialogueLine(
    val id: String,
    val role: String,
    val text: String,
    val translation: String? = null,
    val isUser: Boolean = false
)

data class DialogueSession(
    val sceneId: String,
    val status: String,
    val title: String,
    val lines: List<DialogueLine>,
    val suggestedReply: String
)

data class DialogueTurn(
    val replyText: String,
    val suggestedReply: String,
    val recognizedText: String? = null,
    val replyAudioUrl: String? = null
)

data class LlmModel(
    val id: String,
    val displayName: String,
    val provider: String,
    val description: String
)

data class AppVersion(
    val latestVersion: String,
    val minSupportedVersion: String,
    val apkUrl: String,
    val releaseNotes: String,
    val forceUpdate: Boolean
)

data class Book(
    val id: String,
    val displayName: String,
    val description: String,
    val level: String,
    val lessonCount: Int
)

data class DialogueScene(val id: String, val title: String, val description: String)

data class DailyScore(
    val date: String,
    val avgTotal: Double,
    val avgPronunciation: Double,
    val avgFluency: Double,
    val avgCompleteness: Double,
    val sessions: Int
)

data class PracticeStats(
    val totalSessions: Int,
    val avgTotal: Double,
    val avgPronunciation: Double,
    val avgFluency: Double,
    val avgCompleteness: Double,
    val bestTotal: Double,
    val recentSessions: Int,
    val streakDays: Int,
    val daily: List<DailyScore>,
    val lessonsAttempted: List<Int>,
    val weakestLessons: List<WeakestLesson> = emptyList()
) {
    val hasData: Boolean get() = totalSessions > 0
}

data class LessonProgress(
    val book: String = "nce1",
    val lessonId: Int,
    val attemptCount: Int,
    val bestScore: Double,
    val lastScore: Double,
    val lastPracticedAt: String? = null
) {
    val isPracticed: Boolean get() = attemptCount > 0
}

data class WeakestLesson(
    val book: String = "nce1",
    val lessonId: Int,
    val bestScore: Double,
    val avgScore: Double,
    val attempts: Int
)
