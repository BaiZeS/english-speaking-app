package com.app.english.ui.score

import com.app.english.domain.model.WordScore
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Aggregate result of a completed read-along session, passed from the player
 * to the score-result screen via this singleton holder (avoids passing complex
 * objects through nav args).
 */
data class ScoreSession(
    val lessonTitle: String,
    val roleName: String,
    val totalScore: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    val suggestion: String?,
    val lineCount: Int,
    val lineResults: List<LineScoreResult>
)

data class LineScoreResult(
    val lineId: String,
    val text: String,
    val total: Double,
    val wordScores: List<WordScore>
)

@Singleton
class ScoreSessionHolder @Inject constructor() {
    var session: ScoreSession? = null
}
