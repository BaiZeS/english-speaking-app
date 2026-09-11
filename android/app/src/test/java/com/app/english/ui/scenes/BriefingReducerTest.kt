package com.app.english.ui.scenes

import com.app.english.domain.model.BriefingProgress
import com.app.english.domain.model.BriefingStepState
import com.app.english.domain.model.DrillGradeResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
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

    /**
     * 契约变更(P4): 游标照旧前进(服务端仍是唯一事实来源), 但**屏幕停在刚答过的那
     * 一题**上 —— 以前这条断言组合正是"反馈卡永不出现"的现场: 渲染门比的是
     * `answeredStepId == currentSpec().id`, 而 Graded 在同一次归约里就把 currentSpec
     * 换成了下一题。现在门只看 [BriefingUiState.pendingGrade]。
     */
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
        assertNotNull(next.pendingGrade)
        assertEquals("f1", next.displayedStepId)
        assertTrue(next.isAwaitingFeedback)
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

    // ---- 跳过键文案: 一个原因一句话 -----------------------------------------

    /**
     * 用户报告的第三个症状的回归锁: 松手开始评分的那一刻, 屏幕底部曾宣称
     * "跳过额度已用完", 而同屏右上角还印着 "跳过额度 2/2"。
     */
    @Test
    fun gradingDoesNotClaimQuotaExhausted() {
        val grading = progress(skipsRemaining = 2).toUiState().copy(isSubmitting = true)
        assertEquals(SkipAffordance.Grading, grading.skipAffordance)
        assertFalse(grading.canSkip)
        assertEquals("评分中…", grading.skipLabel)
        // 额度本身一点没动 —— 误报的自证。
        assertEquals(2, grading.skipsRemaining)
    }

    @Test
    fun quotaExhaustedIsTheOnlyStateThatSaysSo() {
        val exhausted = progress(skipsRemaining = 0).toUiState()
        assertEquals(SkipAffordance.NoQuota, exhausted.skipAffordance)
        assertFalse(exhausted.canSkip)
        assertEquals("跳过额度已用完 (每场 2 次)", exhausted.skipLabel)
    }

    @Test
    fun enabledIsTheOnlyStateThatOffersSkipping() {
        val ready = progress(skipsRemaining = 1).toUiState()
        assertEquals(SkipAffordance.Enabled, ready.skipAffordance)
        assertTrue(ready.canSkip)
        assertEquals("跳过这一步", ready.skipLabel)
        assertTrue(ready.showsSkipRow)
    }

    @Test
    fun allStepsDoneSaysCompletedNotQuotaExhausted() {
        val done = progress(statuses = listOf("passed", "passed")).toUiState()
        assertEquals(SkipAffordance.NothingToSkip, done.skipAffordance)
        assertFalse(done.canSkip)
        assertEquals("全部步骤已完成", done.skipLabel)
    }

    @Test
    fun emptyChecklistHidesTheRowInsteadOfInventingAReason() {
        val empty = BriefingUiState()
        assertEquals(SkipAffordance.Restoring, empty.skipAffordance)
        assertFalse(empty.showsSkipRow)
        // 未加载态不得对外宣称还有额度可用。
        assertEquals(0, empty.skipsRemaining)
    }

    // ---- 空快照三态: 加载中 / 加载失败 / 已完成 ------------------------------

    @Test
    fun emptyStepsWhileLoadingSaysRestoring() {
        val state = BriefingUiState(isLoading = true)
        assertEquals("正在恢复会话…", state.emptyStepsExplanation)
        assertFalse(state.needsSnapshotRetry)
    }

    /**
     * 加载失败此前也显示"正在恢复会话…", 于是那一屏**永远在恢复**, 且底部同时
     * 误报额度用完。失败必须给出可重试的错误态。
     */
    @Test
    fun failedLoadOffersRetryInsteadOfRestoringForever() {
        val failed = reduceBriefing(
            BriefingUiState(),
            BriefingEvent.Failed("连不上服务器, 请检查网络或「设置」里的服务器地址。")
        )
        assertFalse(failed.isLoading)
        assertTrue(failed.needsSnapshotRetry)
        assertEquals("打基础清单没能加载出来", failed.emptyStepsExplanation)
        assertFalse(failed.showsSkipRow)
    }

    @Test
    fun restoringEventKeepsTheChecklistAndClearsTheError() {
        val failed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Failed("boom")
        )
        val retrying = reduceBriefing(failed, BriefingEvent.Restoring)
        assertTrue(retrying.isLoading)
        assertNull(retrying.error)
        // 重试不该把已经拿到的清单抹掉。
        assertEquals(3, retrying.steps.size)
    }

    @Test
    fun completedChecklistIsNotMistakenForALoadFailure() {
        val done = progress(statuses = listOf("passed", "passed")).toUiState()
        assertEquals("全部步骤已完成", done.emptyStepsExplanation)
        assertFalse(done.needsSnapshotRetry)
    }
}
