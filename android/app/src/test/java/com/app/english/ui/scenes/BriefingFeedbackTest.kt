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
 * 问题 4(跟读后没有即时反馈)的行为锁, 全部围绕 `pendingGrade` 这个独立槽位:
 * 反馈必须活到学员确认, 而**产生评分的那个事件不能再决定反馈显示在哪一题上**。
 *
 * 这里每一条都是"旧代码全绿却什么都没有"的路径: 过关、最后一步过关、崩溃重进、
 * 高分自动前进、点按取消。渲染门以前比的是 `answeredStepId == spec.id`, 而同一次
 * 归约已经把游标推到下一题了, 所以只有不及格(<60)看得到反馈 —— 旧的唯一用例恰好
 * 是不及格, 于是测试全绿、真机全无反馈。
 */
class BriefingFeedbackTest {
    private fun progress(
        statuses: List<String> = listOf("pending", "pending", "pending"),
        grades: Map<Int, DrillGradeResult> = emptyMap()
    ): BriefingProgress = BriefingProgress(
        total = statuses.size,
        done = statuses.count { it != "pending" },
        skipsRemaining = 2,
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

    /** 过关的反馈必须活到学员确认, 而不是被换题静静顶掉。 */
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

    /**
     * 拉快照的那一刻如果反馈正挂着, 不能把它抹掉。眼下的界面没有"边看反馈边刷新"的
     * 入口, 但这条不变式很便宜, 而违背它的代价正是问题 4 的另一面 —— 反馈在阅读途中
     * 被静默抽走。
     */
    @Test
    fun refreshingTheSnapshotWhileReadingFeedbackKeepsItOnScreen() {
        val dwelling = reduceBriefing(
            progress().toUiState(),
            BriefingEvent.Graded(
                grade(score = 72.0),
                briefing = progress(statuses = listOf("passed", "pending", "pending"))
            )
        )
        val refreshed = reduceBriefing(
            dwelling,
            BriefingEvent.Loaded(progress(statuses = listOf("passed", "pending", "pending")))
        )
        assertNotNull(refreshed.pendingGrade)
        assertEquals("f1", refreshed.displayedStepId)
        assertEquals(1, refreshed.currentIndex)
        // 快照里没有这一步的 last_grade 时也照样留着, 由学员自己点继续。
        val cleared = reduceBriefing(refreshed, BriefingEvent.FeedbackAcknowledged)
        assertNull(cleared.pendingGrade)
        assertEquals("f2", cleared.answerableStepId)
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
        // 恢复出来的这张卡必须还能动作: 撤掉停留后这一步就能重录。
        val acknowledged = reduceBriefing(resumed, BriefingEvent.FeedbackAcknowledged)
        assertEquals("f2", acknowledged.answerableStepId)
        assertEquals("f2", acknowledged.displayedStepId)
    }

    @Test
    fun aResumedResubmittableStepCanChainGradeAcknowledgeGrade() {
        val failed = grade(score = 45.0, passed = false, stepId = "f1")
        val resumed = progress(
            statuses = listOf("pending", "pending"),
            grades = mapOf(0 to failed)
        ).toUiState()
        // 摆回反馈 -> 学员看清问题 -> 「再试一次」确认 -> 录音键就在下面。
        assertEquals("f1", resumed.displayedStepId)
        assertEquals("f1", resumed.answerableStepId)
        val acknowledged = reduceBriefing(resumed, BriefingEvent.FeedbackAcknowledged)
        assertEquals("f1", acknowledged.answerableStepId)
        // 再答一次, 反馈又来一张。
        val again = reduceBriefing(
            acknowledged,
            BriefingEvent.Graded(
                grade(score = 66.0, stepId = "f1"),
                briefing = progress(statuses = listOf("passed", "pending"))
            )
        )
        assertEquals("f1", again.displayedStepId)
        assertNull(again.answerableStepId)
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
}
