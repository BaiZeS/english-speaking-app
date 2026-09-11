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
        skipsRemaining: Int = 2,
        grades: Map<Int, DrillGradeResult> = emptyMap()
    ): BriefingProgress = BriefingProgress(
        total = statuses.size,
        done = statuses.count { it != "pending" },
        skipsRemaining = skipsRemaining,
        unlockedMission = statuses.isNotEmpty() && statuses.all { it != "pending" },
        steps = statuses.mapIndexed { index, status ->
            val lastGrade = grades[index]
            BriefingStepState(
                id = "f${index + 1}",
                index = index,
                type = "translate",
                status = status,
                lastGrade = lastGrade,
                lastScore = lastGrade?.score
            )
        }
    )

    private fun grade(score: Double, passed: Boolean = score >= 60, stepId: String = "f1") =
        DrillGradeResult(
            stepId = stepId,
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

    /** 问题 4 的回归锁: 过关的反馈必须活到学员确认, 而不是被换题静静顶掉。 */
    @Test
    fun passingGradeKeepsFeedbackVisibleUntilAcknowledged() {
        val passed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                // 89 分会武装倒计时, 这条只验"确认前不消失", 用 70 分保持手动。
                grade(score = 70.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        assertEquals(1, passed.currentIndex)
        assertNotNull(passed.pendingGrade)
        assertEquals("f1", passed.displayedStepId)

        val acknowledged = reduceBriefing(passed, BriefingEvent.FeedbackAcknowledged)
        assertNull(acknowledged.pendingGrade)
        assertFalse(acknowledged.isAwaitingFeedback)
        // 确认后交还游标: 屏幕落到下一题, 而游标本身一直是服务端给的那个。
        assertEquals("f2", acknowledged.displayedStepId)
        assertEquals(1, acknowledged.currentIndex)
    }

    /**
     * 最后一步过关: `currentStep == null`, 旧渲染门上那条 `|| currentStep == null`
     * 分支永远走不到(题卡提前 return), 所以这一步的反馈从来没出现过。
     */
    @Test
    fun lastStepPassStillShowsFeedback() {
        val done = reduceBriefing(
            progress(statuses = listOf("passed", "passed", "pending")).toUiState(),
            BriefingEvent.Graded(
                grade(score = 91.0, stepId = "f3"),
                briefing = progress(statuses = listOf("passed", "passed", "passed"))
            )
        )
        assertNull(done.currentStep)
        assertEquals(-1, done.currentIndex)
        assertNotNull(done.pendingGrade)
        assertEquals("f3", done.displayedStepId)
        assertEquals("f3", done.steps.last().id)
    }

    @Test
    fun feedbackDwellBlocksSubmittingTheStepThatIsNotOnScreen() {
        val passed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 70.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        // 屏上显示 f1(已 passed), 服务端只收 f2 —— 两者不同时提交口必须闭嘴,
        // 否则要么 409 STEP_ALREADY_DONE, 要么提交一道屏幕上没有的题。
        assertEquals("f1", passed.displayedStepId)
        assertNull(passed.answerableStepId)
        val acknowledged = reduceBriefing(passed, BriefingEvent.FeedbackAcknowledged)
        assertEquals("f2", acknowledged.answerableStepId)
    }

    @Test
    fun retryIsOfferedOnlyWhileTheAnsweredStepIsStillPending() {
        val failed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(grade(score = 40.0, passed = false), briefing = progress())
        )
        assertTrue(
            "不及格那一步服务端留在 pending, 「再试一次」是真选项",
            failed.canRetryAnsweredStep
        )
        val passed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 70.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        assertFalse(
            "已过关的步再提交只会吃 409 STEP_ALREADY_DONE, 不该给这个键",
            passed.canRetryAnsweredStep
        )
    }

    // ---- 自动前进: 达到优秀线才倒数, 点按只撤秒针 ----------------------------

    @Test
    fun excellentGradeArmsTheCountdownAndPassingItStaysManual() {
        val excellent = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 92.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        assertEquals(FeedbackAdvancePolicy.countdownSeconds(), excellent.autoAdvanceSeconds)
        assertTrue(
            excellent.autoAdvanceHint.startsWith(
                "${FeedbackAdvancePolicy.countdownSeconds()} 秒后自动继续"
            )
        )

        val justPassed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 84.9),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        assertNull(justPassed.autoAdvanceSeconds)
        assertEquals("", justPassed.autoAdvanceHint)
    }

    @Test
    fun tickingTheCountdownDownAdvancesTheCursorWhenItRunsOut() {
        var state = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 96.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        repeat(FeedbackAdvancePolicy.countdownSeconds() - 1) {
            state = reduceBriefing(state, BriefingEvent.AutoAdvanceTick)
            assertNotNull("倒数途中反馈不能被撤走", state.pendingGrade)
        }
        assertEquals(1, state.autoAdvanceSeconds)
        val expired = reduceBriefing(state, BriefingEvent.AutoAdvanceTick)
        // 自然走完 == 自动前进: 反馈撤下, 游标交还下一题。
        assertNull(expired.pendingGrade)
        assertEquals("f2", expired.displayedStepId)
        assertNull(expired.autoAdvanceSeconds)
    }

    /**
     * D10 的取消语义: 滚动/点按撤掉的是**倒计时**, 不是反馈。到期与取消必须是两条
     * 不同的转换 —— 到期才前进, 取消绝不前进。
     */
    @Test
    fun cancellingTheCountdownKeepsTheFeedbackOnScreen() {
        val armed = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 99.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        val cancelled = reduceBriefing(armed, BriefingEvent.AutoAdvanceCancelled)
        assertNull(cancelled.autoAdvanceSeconds)
        assertEquals("", cancelled.autoAdvanceHint)
        assertNotNull(cancelled.pendingGrade)
        assertEquals("f1", cancelled.displayedStepId)
        // 取消后秒针再被推一次也不能把反馈偷走(过期任务/重复事件的兜底)。
        val afterStrayTick = reduceBriefing(cancelled, BriefingEvent.AutoAdvanceTick)
        assertNotNull(afterStrayTick.pendingGrade)
        assertEquals("f1", afterStrayTick.displayedStepId)
    }

    /**
     * `/skip-step` 复用同一条响应形状: `score=0` + `passed=true` + `llm_source="skip"`。
     * 反馈卡因此要认得出"这是跳过, 不是 0 分", 并且**绝不**自动前进 —— 那 5 秒是留给
     * 读真实反馈的, 不是一份占位数据。
     */
    @Test
    fun aSkippedStepIsNotPresentationallyAZeroScore() {
        val skipped = DrillGradeResult(
            stepId = "f1",
            stepType = "read_along",
            score = 0.0,
            passed = true,
            passScore = 60.0,
            feedbackCn = "已跳过这一步 (每场最多跳 2 步)。",
            source = "stub",
            llmSource = "skip"
        )
        assertTrue(skipped.isSkipped)
        assertFalse(skipped.isRealEvidence)
        val next = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                skipped,
                briefing = progress(statuses = listOf("skipped", "pending", "pending"))
            )
        )
        assertNull(next.autoAdvanceSeconds)
        assertEquals("", next.autoAdvanceHint)
        assertFalse(next.canRetryAnsweredStep)
        assertEquals("f1", next.displayedStepId)
    }

    // ---- 崩溃恢复: 服务端逐步留档的 last_grade ------------------------------

    /**
     * 重进/崩溃恢复时把服务端为这一步存下的完整反馈原样摆回 —— 只剩一个分数等于
     * 把「刚才那句到底哪儿读错了」整份丢掉。
     */
    @Test
    fun resumeRestoresLastGradeFromSnapshot() {
        val failedAttempt = grade(score = 45.0, passed = false, stepId = "f2")
        val resumed = progress(
            statuses = listOf("passed", "pending", "pending"),
            grades = mapOf(1 to failedAttempt)
        ).toUiState()
        assertEquals(1, resumed.currentIndex)
        assertNotNull(resumed.pendingGrade)
        assertEquals("f2", resumed.displayedStepId)
        assertEquals(45.0, resumed.pendingGrade!!.score, 0.0)
        // 重进不是"刚读完", 所以不自作主张倒数把反馈抽走。
        assertNull(resumed.autoAdvanceSeconds)
        assertTrue(resumed.canRetryAnsweredStep)
    }

    @Test
    fun resumeAfterAllStepsDoneShowsTheLastGradedStep() {
        val last = grade(score = 88.0, stepId = "f3")
        val resumed = progress(
            statuses = listOf("skipped", "passed", "passed"),
            grades = mapOf(2 to last)
        ).toUiState()
        assertNull(resumed.currentStep)
        assertEquals("f3", resumed.displayedStepId)
        assertNull(resumed.answerableStepId)
    }

    @Test
    fun resumeWithoutAnyGradeStaysClean() {
        val resumed = progress().toUiState()
        assertNull(resumed.pendingGrade)
        assertNull(resumed.lastGrade)
        assertEquals("f1", resumed.displayedStepId)
        assertEquals("f1", resumed.answerableStepId)
    }

    // ---- 反馈卡要显示的东西: 五维 null 不是 0 --------------------------------

    @Test
    fun subScoresRenderOnlyDimensionsWithEvidence() {
        val grade = DrillGradeResult(
            stepId = "f1",
            stepType = "read_along",
            score = 77.0,
            passed = true,
            passScore = 60.0,
            feedbackCn = "",
            pronunciation = 81.0,
            fluency = null, // 这一轮 ISE 没跑起来 = 无证据, 不是 0 分
            completeness = 64.0,
            grammar = null,
            vocabulary = 70.0,
            source = "xunfei"
        )
        val readout = drillSubScoreReadout(grade)
        assertEquals(
            listOf("发音" to 81.0, "完整" to 64.0, "词汇" to 70.0),
            readout.map { it.label to it.score }
        )
    }

    @Test
    fun fiveDimensionsAllPresentAreKeptInReadingOrder() {
        val grade = DrillGradeResult(
            stepId = "f1",
            stepType = "translate",
            score = 60.0,
            passed = true,
            passScore = 60.0,
            feedbackCn = "",
            pronunciation = 1.0,
            fluency = 2.0,
            completeness = 3.0,
            grammar = 4.0,
            vocabulary = 5.0
        )
        assertEquals(
            listOf("发音", "流利", "完整", "语法", "词汇"),
            drillSubScoreReadout(grade).map { it.label }
        )
        val noEvidence = grade.copy(
            pronunciation = null,
            fluency = null,
            completeness = null,
            grammar = null,
            vocabulary = null
        )
        assertTrue(drillSubScoreReadout(noEvidence).isEmpty())
    }

    // ---- 进度点: 已收到的分数要看得见 ----------------------------------------

    @Test
    fun progressDotPrefersBestScoreOverLastScore() {
        val step = BriefingStepUi(
            id = "f1",
            index = 0,
            type = "read_along",
            status = "passed",
            attempts = 3,
            bestScore = 92.0,
            lastScore = 71.0
        )
        assertEquals(92.0, step.dotScore!!, 0.0)
        assertEquals("×3", step.dotAttempts)
    }

    @Test
    fun progressDotFallsBackToLastScoreAndStaysSilentOnASingleAttempt() {
        val step = BriefingStepUi(
            id = "f1",
            index = 0,
            type = "read_along",
            status = "pending",
            attempts = 1,
            lastScore = 48.0
        )
        assertEquals(48.0, step.dotScore!!, 0.0)
        assertNull(step.dotAttempts)
        val untouched = step.copy(attempts = 0, lastScore = null)
        assertNull(untouched.dotScore)
        assertNull(untouched.dotAttempts)
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
