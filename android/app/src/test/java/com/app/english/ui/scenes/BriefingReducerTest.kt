package com.app.english.ui.scenes

import com.app.english.domain.model.BriefingProgress
import com.app.english.domain.model.BriefingStepState
import com.app.english.domain.model.DrillGradeResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 打基础状态机 reducer 的行为锁(T7 质量门): 60 过关前进 / 60 以下不拦只警示 /
 * 跳过额度用完前置禁用 / 恢复快照整表重建。
 */
class BriefingReducerTest {
    private fun progress(
        statuses: List<String> = listOf("pending", "pending", "pending"),
        skipsRemaining: Int = 2
    ): BriefingProgress = BriefingProgress(
        total = statuses.size,
        done = statuses.count { it != "pending" },
        skipsRemaining = skipsRemaining,
        unlockedMission = statuses.isNotEmpty() && statuses.all { it != "pending" },
        steps = statuses.mapIndexed { index, status ->
            BriefingStepState(
                id = "f${index + 1}",
                index = index,
                type = "translate",
                status = status
            )
        }
    )

    private fun grade(score: Double, passed: Boolean = score >= 60) = DrillGradeResult(
        stepId = "f1",
        stepType = "translate",
        score = score,
        passed = passed,
        passScore = 60.0,
        feedbackCn = "",
        source = "llm"
    )

    @Test
    fun loadedSnapshotBuildsTheWholeTableAndPicksFirstPending() {
        val state = progress(statuses = listOf("passed", "pending", "pending")).toUiState()
        assertEquals(1, state.currentIndex)
        assertEquals(3, state.steps.size)
        assertTrue(state.canSkip)
        assertNull(state.lastGrade)
    }

    @Test
    fun passingGradeAdvancesTheCursor() {
        val start = progress().toUiState()
        val outcome = BriefingEvent.Graded(
            grade(score = 88.0),
            briefing = progress(
                statuses = listOf("passed", "pending", "pending")
            )
        )
        val next = reduceBriefing(start.copy(isSubmitting = true), outcome)
        assertEquals(1, next.currentIndex)
        assertEquals("f1", next.answeredStepId)
        assertFalse(next.isSubmitting)
        assertTrue(next.lastGrade!!.passed)
    }

    @Test
    fun failingGradeDoesNotBlockAndKeepsTheCursor() {
        val start = progress().toUiState()
        val next = reduceBriefing(
            start,
            BriefingEvent.Graded(grade(score = 40.0, passed = false), briefing = progress())
        )
        assertEquals(0, next.currentIndex)
        assertFalse(next.lastGrade!!.passed)
        // 不拦: 当前步仍是 pending, 学员可以重录。
        assertEquals("pending", next.steps[0].status)
    }

    @Test
    fun skipBudgetExhaustedDisablesSkipBeforeThe409() {
        val start = progress(
            statuses = listOf("pending", "pending"),
            skipsRemaining = 0
        ).toUiState()
        assertFalse(start.canSkip)
        val afterOneSkip = progress(statuses = listOf("skipped", "pending"), skipsRemaining = 1)
            .toUiState()
        assertTrue(afterOneSkip.canSkip)
        assertEquals(1, afterOneSkip.currentIndex)
    }

    @Test
    fun failedSubmissionClearsBackToIdle() {
        val start = progress().toUiState().copy(isSubmitting = true)
        val next = reduceBriefing(start, BriefingEvent.Failed("音频无法转写"))
        assertFalse(next.isSubmitting)
        assertEquals("音频无法转写", next.error)
        assertEquals(0, next.currentIndex)
        val cleared = reduceBriefing(next, BriefingEvent.ErrorShown)
        assertNull(cleared.error)
    }

    @Test
    fun unlockedMissionSurvivesTheReduction() {
        val next = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 70.0),
                briefing = progress(statuses = listOf("passed", "skipped", "passed"))
            )
        )
        assertTrue(next.unlockedMission)
        assertEquals(-1, next.currentIndex)
        assertNull(next.currentStep)
    }
}
