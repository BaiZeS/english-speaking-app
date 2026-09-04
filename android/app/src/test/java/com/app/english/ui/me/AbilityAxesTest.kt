package com.app.english.ui.me

import com.app.english.domain.model.PracticeStats
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** 四维画像的取值/缺证据语义(P5 用 /stats 临时喂雷达, P7 换成 GET /ability)。 */
class AbilityAxesTest {
    private fun stats(
        totalSessions: Int = 5,
        pronunciation: Double = 82.0,
        fluency: Double = 74.0
    ) = PracticeStats(
        totalSessions = totalSessions,
        avgTotal = 80.0,
        avgPronunciation = pronunciation,
        avgFluency = fluency,
        avgCompleteness = 78.0,
        bestTotal = 95.0,
        recentSessions = 2,
        streakDays = 3,
        daily = emptyList(),
        lessonsAttempted = emptyList()
    )

    @Test
    fun axisLabelsMatchThePlan() {
        assertEquals(listOf("发音", "语法", "词汇", "流利度"), AbilityAxes.LABELS)
    }

    @Test
    fun scoresAreNormalisedToRadiusFractions() {
        val axes = AbilityAxes(
            pronunciation = 85.0,
            grammar = 60.0,
            vocabulary = 40.0,
            fluency = 100.0
        )
        assertEquals(listOf(0.85f, 0.60f, 0.40f, 1.00f), axes.radarValues().map { round(it) })
    }

    @Test
    fun outOfRangeScoresClampInsideTheCircle() {
        val axes = AbilityAxes(pronunciation = 250.0, grammar = -20.0)
        val values = axes.radarValues()
        assertEquals(1f, values.first(), 0f)
        assertEquals(0f, values[1], 0f)
    }

    @Test
    fun provisionalProfileLeavesGrammarAndVocabularyEmpty() {
        val axes = AbilityAxes.fromStats(stats())
        assertEquals(82.0, axes.pronunciation ?: -1.0, 0.0)
        assertEquals(74.0, axes.fluency ?: -1.0, 0.0)
        assertEquals(null, axes.grammar)
        assertEquals(null, axes.vocabulary)
        assertFalse("语法/词汇要等 P3/P4 后端才有线上证据", axes.isComplete)
        assertTrue(axes.hasAnyEvidence)
        assertEquals(listOf("语法", "词汇"), axes.missingLabels())
        // 缺失维度贴着圆心, 不会被画成 0 分之外的任何东西
        assertEquals(listOf(0.82f, 0f, 0f, 0.74f), axes.radarValues().map { round(it) })
    }

    @Test
    fun noPracticeNoEvidence() {
        listOf(null, stats(totalSessions = 0)).forEach { source ->
            val axes = AbilityAxes.fromStats(source)
            assertTrue(axes.isEmpty)
            assertFalse(axes.hasAnyEvidence)
            assertFalse(axes.isComplete)
            assertEquals(listOf(0f, 0f, 0f, 0f), axes.radarValues().map { round(it) })
            assertEquals(AbilityAxes.LABELS, axes.missingLabels())
        }
    }

    @Test
    fun completeProfileNeedsAllFourDimensions() {
        val axes = AbilityAxes(90.0, 80.0, 70.0, 60.0)
        assertTrue(axes.isComplete)
        assertFalse(axes.isEmpty)
        assertTrue(axes.missingLabels().isEmpty())
    }

    private fun round(value: Float): Float = Math.round(value * 10000f) / 10000f
}
