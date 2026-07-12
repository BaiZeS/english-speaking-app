package com.app.english.domain

/**
 * Feedback band for a score value, per spec §5.3.
 * - GREEN: score >= 85
 * - YELLOW: 60 <= score < 85
 * - RED: score < 60
 */
enum class ScoreLevel {
    GREEN,
    YELLOW,
    RED
}

object ScoreColorMapper {
    const val GREEN_THRESHOLD: Double = 85.0
    const val YELLOW_THRESHOLD: Double = 60.0

    fun level(score: Double): ScoreLevel = when {
        score >= GREEN_THRESHOLD -> ScoreLevel.GREEN
        score >= YELLOW_THRESHOLD -> ScoreLevel.YELLOW
        else -> ScoreLevel.RED
    }
}
