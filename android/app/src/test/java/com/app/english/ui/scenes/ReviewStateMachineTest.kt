package com.app.english.ui.scenes

import com.app.english.domain.model.ReviewReportData
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 复盘页三态与轮询去留的锁(§P6 客户端 7/8)。
 *
 * 这些用例存在的意义是一条生产事实: 一次总评 LLM 烧掉 ~68s(`review copy degraded to
 * deterministic` 打在请求后 68s), 而手机 OkHttp `readTimeout` 是 30s —— 结果是**服务端
 * 把活干完了、报告也落库了, 学员却永远看不到**。异步化把这件事拆成"数值立刻可见 + 文案
 * 随后补", 而拆开的代价是页面多了一整套易写错的判断, 所以判断本身抽成纯函数锁在这里。
 */
class ReviewStateMachineTest {

    // ===== 轮询去留 =====

    @Test
    fun generatingGetsTheBackoffCadenceAndNothingElse() {
        val step = ReviewStateMachine.nextPollStep(
            pollCount = 0,
            elapsedMillis = 0L,
            status = ReviewPollingPolicy.STATUS_GENERATING,
            consecutiveFailures = 0
        )
        assertEquals(
            ReviewPollStep.Wait(ReviewPollingPolicy.FAST_POLL_MILLIS),
            step
        )
    }

    @Test
    fun terminalStatusesStopImmediatelyWithoutWaitingForTheTimeout() {
        for (status in listOf(
            ReviewPollingPolicy.STATUS_READY,
            ReviewPollingPolicy.STATUS_FAILED
        )) {
            assertEquals(
                "status=$status",
                ReviewPollStep.Stop,
                ReviewStateMachine.nextPollStep(1, 1_000L, status, 0)
            )
        }
    }

    /**
     * 一个认不出来的状态字符串**绝不能**让循环挂着: 后端刻意把它声明成 `str | None`(住在
     * JSON 列里, 脏值不该把 GET 打成 500), 那客户端就得假定脏值真的会出现。脏值挂住循环
     * 就是"总体评价永远不出来"换了个形状。
     */
    @Test
    fun dirtyStatusStopsTheLoopInsteadOfSpinningForever() {
        for (dirty in listOf(null, "", "running", "pending", "GENERATING", " done ", "42")) {
            assertEquals(
                "status=$dirty",
                ReviewPollStep.Stop,
                ReviewStateMachine.nextPollStep(0, 0L, dirty, 0)
            )
        }
    }

    @Test
    fun giveUpWindowIsThePollingPolicysAndNotSomethingInventedHere() {
        val almost = ReviewPollingPolicy.TIMEOUT_MILLIS - 1
        assertFalse(
            ReviewPollingPolicy.isTimedOut(almost) ||
                ReviewStateMachine.nextPollStep(0, almost, ReviewPollingPolicy.STATUS_GENERATING, 0)
                    is ReviewPollStep.GaveUp
        )
        assertTrue(
            ReviewStateMachine.nextPollStep(
                0,
                ReviewPollingPolicy.TIMEOUT_MILLIS,
                ReviewPollingPolicy.STATUS_GENERATING,
                0
            ) is ReviewPollStep.GaveUp
        )
    }

    /** 超时排在网络失败之前: 两者同时成立时, 页面上该说的是"等太久"而不是"断网了"。 */
    @Test
    fun timeoutOutranksNetworkTrouble() {
        val step = ReviewStateMachine.nextPollStep(
            pollCount = 9,
            elapsedMillis = ReviewPollingPolicy.TIMEOUT_MILLIS,
            status = ReviewPollingPolicy.STATUS_GENERATING,
            consecutiveFailures = 5
        )
        assertEquals(ReviewPollStep.Reason.TIMEOUT, (step as ReviewPollStep.GaveUp).reason)
    }

    /** 单次丢包放过, 连续两次就放弃 —— 与 `GenerateCourseViewModel` 同一条纪律。 */
    @Test
    fun onePollFailureIsTreatedAsNetworkJitter() {
        val status = ReviewPollingPolicy.STATUS_GENERATING
        assertTrue(
            ReviewStateMachine.nextPollStep(2, 20_000L, status, 1) is ReviewPollStep.Wait
        )
        val step = ReviewStateMachine.nextPollStep(2, 20_000L, status, 2)
        assertEquals(ReviewPollStep.Reason.NETWORK, (step as ReviewPollStep.GaveUp).reason)
    }

    // ===== 三态渲染 =====

    /**
     * 第三态的核心: `generating` 时数值**照常渲染**, 只有文案区是进度。整页 spinner
     * 会把学员已经到手的成绩藏起来 —— 那正是原来的超时页给人的感觉("我这一场白练了")。
     */
    @Test
    fun generatingStillPaintsTheNumbers() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(
                status = ReviewPollingPolicy.STATUS_GENERATING,
                hasReport = true,
                pollInFlight = true
            )
        )
        assertEquals(ReviewPhase.GENERATING, phase)
        assertTrue(ReviewStateMachine.paintsReportSkeleton(phase))
        assertNotNull(ReviewStateMachine.proseHintOf(phase, 0L))
    }

    @Test
    fun theGeneratingHintComesFromThePollingPolicysOwnWording() {
        // 早期与晚期两档, 都由 ReviewPollingPolicy 说话: 页面不许自己编一套进度文案。
        assertEquals(
            ReviewPollingPolicy.stageText(0L),
            ReviewStateMachine.proseHintOf(ReviewPhase.GENERATING, 0L)
        )
        assertEquals(
            ReviewPollingPolicy.stageText(ReviewPollingPolicy.TIMEOUT_MILLIS),
            ReviewStateMachine.proseHintOf(
                ReviewPhase.GENERATING,
                ReviewPollingPolicy.TIMEOUT_MILLIS
            )
        )
        assertEquals("AI 正在写总评…", ReviewStateMachine.proseHintOf(ReviewPhase.GENERATING, 0L))
    }

    /** ready 的判据**不是** `source`: LLM 挂着时终态是 `ready` + `heuristic`, 那已是诚实的最终答案。 */
    @Test
    fun readyHeuristicIsTheFinalAnswerNotAWaitingRoom() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(status = ReviewPollingPolicy.STATUS_READY, hasReport = true)
        )
        assertEquals(ReviewPhase.FINAL, phase)
        assertNull(ReviewStateMachine.proseHintOf(phase, 0L))
        // 降级横幅该出现(source != llm), 但它说的是"文案是规则拼的", 不是"还在生成"。
        assertTrue(ReviewStateMachine.showDegradedBanner(phase, "heuristic"))
        assertFalse(ReviewStateMachine.showDegradedBanner(phase, "llm"))
    }

    /** 生成中**不**挂降级横幅: 数值骨架的 `source` 恒为 heuristic, 那时挂它就是在撒谎。 */
    @Test
    fun generatingDoesNotClaimTheCopyIsAlreadyDeterministic() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(
                status = ReviewPollingPolicy.STATUS_GENERATING,
                hasReport = true,
                pollInFlight = true
            )
        )
        assertFalse(ReviewStateMachine.showDegradedBanner(phase, "heuristic"))
    }

    @Test
    fun dirtyOrAbsentStatusWithAReportInHandRendersIt() {
        for (status in listOf(null, "", "queued", "UNKNOWN")) {
            val phase = ReviewStateMachine.phaseOf(
                ReviewPhaseInput(status = status, hasReport = true)
            )
            assertEquals("status=$status", ReviewPhase.FINAL, phase)
        }
    }

    @Test
    fun failedJobKeepsTheNumbersAndOffersTheRetry() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(status = ReviewPollingPolicy.STATUS_FAILED, hasReport = true)
        )
        assertEquals(ReviewPhase.COPY_FAILED, phase)
        assertTrue(ReviewStateMachine.paintsReportSkeleton(phase))
        assertNotNull(ReviewStateMachine.retryCopyLabelOf(phase))
        assertNotNull(ReviewStateMachine.proseHintOf(phase, 0L))
    }

    @Test
    fun givingUpWhileGeneratingTurnsTheWaitIntoARetryableNote() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(
                status = ReviewPollingPolicy.STATUS_GENERATING,
                hasReport = true,
                gaveUpWhileGenerating = true
            )
        )
        assertEquals(ReviewPhase.WAIT_TIMED_OUT, phase)
        assertTrue(ReviewStateMachine.paintsReportSkeleton(phase))
        assertNotNull(ReviewStateMachine.retryCopyLabelOf(phase))
    }

    /** 进度态不该多一颗"按了只是再 GET 一次"的键; 放弃态必须有。 */
    @Test
    fun onlyTheAbandonedStatesGetTheCopyRetryKey() {
        assertNull(ReviewStateMachine.retryCopyLabelOf(ReviewPhase.GENERATING))
        assertNull(ReviewStateMachine.retryCopyLabelOf(ReviewPhase.FINAL))
        assertNull(ReviewStateMachine.retryCopyLabelOf(ReviewPhase.LOADING))
        assertNotNull(ReviewStateMachine.retryCopyLabelOf(ReviewPhase.WAIT_TIMED_OUT))
        assertNotNull(ReviewStateMachine.retryCopyLabelOf(ReviewPhase.COPY_FAILED))
    }

    @Test
    fun nothingToRenderIsTheOnlyWholePageError() {
        val waiting = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(status = null, hasReport = false, firstLoadInFlight = true)
        )
        assertEquals(ReviewPhase.LOADING, waiting)
        assertFalse(ReviewStateMachine.paintsReportSkeleton(waiting))
        assertNull(ReviewStateMachine.errorMessageOf(waiting, null))

        val empty = ReviewStateMachine.phaseOf(ReviewPhaseInput(status = null, hasReport = false))
        assertEquals(ReviewPhase.NOTHING_TO_RENDER, empty)
        // 整页错误态自带重试按钮(ErrorState), 所以文案区不再重复放一颗。
        assertNotNull(ReviewStateMachine.errorMessageOf(empty, null))
        assertNull(ReviewStateMachine.retryCopyLabelOf(empty))
        // 网络原因说的话优先于兜底文案, 且绝不能是裸英文(见 BackendErrorTextTest)。
        assertEquals("连不上服务器", ReviewStateMachine.errorMessageOf(empty, "连不上服务器"))
    }

    /** 骨架没到手而循环还在等 = 继续转圈, 不要急着报"没有报告"。 */
    @Test
    fun stillWaitingForTheSkeletonIsLoadingNotMissing() {
        val phase = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(
                status = ReviewPollingPolicy.STATUS_GENERATING,
                hasReport = false,
                pollInFlight = true
            )
        )
        assertEquals(ReviewPhase.LOADING, phase)
    }

    // ===== overall == null 时圆环中心画什么(§P6 次因) =====

    @Test
    fun evidenceNoteReplacesTheBareDashWhenThereIsNothingToScore() {
        val note = "本场缺少可信评分证据, 暂无法给出总分。"
        assertEquals(note, ReviewStateMachine.overallCenterText(null, note))
        // 是句子就得降字号, 否则一句中文会把 140dp 的圆环撑爆。
        assertTrue(ReviewStateMachine.overallCenterIsSentence(null, note))
    }

    @Test
    fun theDashSurvivesOnlyWhenTheBackendGaveNoExplanationEither() {
        assertEquals("—", ReviewStateMachine.overallCenterText(null, ""))
        assertFalse(ReviewStateMachine.overallCenterIsSentence(null, ""))
    }

    @Test
    fun aRealScoreWinsOverAnyNote() {
        // 有分就画分: note 只在 overall 为 null 时才有意义, 反过来会把 75 分说成"没证据"。
        assertEquals("75", ReviewStateMachine.overallCenterText(75.4, "本场缺少可信评分证据"))
        assertFalse(ReviewStateMachine.overallCenterIsSentence(75.4, "本场缺少可信评分证据"))
    }

    /** 圆环画 "0" 与画 "—" 是两种意思: 0 是真考砸了, 别把它跟"没证据"混成一个。 */
    @Test
    fun zeroIsRenderedAsZeroNotAsADash() {
        assertEquals("0", ReviewStateMachine.overallCenterText(0.0, ""))
    }

    // ===== ViewModel 自己那一层怎么把标志喂给上面的决策 =====
    //
    // `ReviewUiState.phase` 是本页**唯一**的判断出口, 而它由四个布尔/字符串组合而成。
    // 组合写错(比如把"放弃等待"忘了传)在 Compose 里完全看不出来 —— 页面照样有分数,
    // 只是那颗该出现的重试键永远不出现。所以锁在状态类上, 而不是只锁纯函数。

    private fun report(overall: Double? = 80.0, source: String = "heuristic") = ReviewReportData(
        sessionId = "s1",
        sceneId = "scene_ordering_coffee",
        title = "咖啡店点单",
        cleared = true,
        autoFinished = false,
        turnCount = 6,
        maxTurns = 14,
        overall = overall,
        dims = emptyMap(),
        pronunciationSubs = emptyMap(),
        highlights = emptyList(),
        improvements = emptyList(),
        checklist = emptyList(),
        transcriptPairs = emptyList(),
        newTokens = emptyList(),
        abilityDelta = emptyMap(),
        hintsUsed = 0,
        source = source,
        llmSource = null
    )

    @Test
    fun generatingSnapshotRendersNumbersWhileTheLoopRuns() {
        val state = ReviewUiState(
            isLoading = false,
            report = report(),
            reviewStatus = ReviewPollingPolicy.STATUS_GENERATING,
            isPolling = true
        )
        assertEquals(ReviewPhase.GENERATING, state.phase)
    }

    @Test
    fun abandonedWaitExposesTheRetryThroughTheState() {
        val state = ReviewUiState(
            isLoading = false,
            report = report(),
            reviewStatus = ReviewPollingPolicy.STATUS_GENERATING,
            isPolling = false,
            gaveUpWaitingForCopy = true
        )
        assertEquals(ReviewPhase.WAIT_TIMED_OUT, state.phase)
        assertNotNull(ReviewStateMachine.retryCopyLabelOf(state.phase))
    }

    /** 未收工/旧快照(`review_status` 缺席)且没有报告: 整页可重试, 且绝不进轮询。 */
    @Test
    fun aLegacySnapshotWithNoReportIsARetryableErrorNotAnInfiniteWait() {
        val state = ReviewUiState(isLoading = false, reviewStatus = null, report = null)
        assertEquals(ReviewPhase.NOTHING_TO_RENDER, state.phase)
        assertEquals(
            ReviewPollStep.Stop,
            ReviewStateMachine.nextPollStep(0, 0L, state.reviewStatus, 0)
        )
    }

    /** 脏值 + 报告在手 -> 当作定稿渲染; 脏值 + 没报告 -> 可重试错误。两种都不轮。 */
    @Test
    fun anUnknownStatusNeverLeavesThePageWaiting() {
        for (dirty in listOf("queued", "DONE", "running", " ")) {
            val withReport = ReviewUiState(
                isLoading = false,
                report = report(),
                reviewStatus = dirty,
                isPolling = true
            )
            assertEquals("status=$dirty", ReviewPhase.FINAL, withReport.phase)
            assertFalse(
                "status=$dirty",
                ReviewStateMachine.proseHintOf(withReport.phase, 0L) != null &&
                    ReviewPollingPolicy.shouldKeepPolling(dirty)
            )
            // 循环一停(脏值不让它继续), 没有报告就只能是**可重试错误态**而不是永远转圈。
            val empty = withReport.copy(report = null, isPolling = false)
            assertEquals("status=$dirty", ReviewPhase.NOTHING_TO_RENDER, empty.phase)
        }
    }
}
