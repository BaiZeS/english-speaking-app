package com.app.english.ui.scenes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 总评轮询节奏锁 —— 生产实测一次总评 LLM 烧掉 ~68s(`review copy degraded to
 * deterministic` 于请求后 68s 打出), 客户端 readTimeout 只有 30s, 所以收工必须
 * 转成"先返回、再轮询"; 本测试钉住轮询窗口确实容得下那个真实时延。
 */
class ReviewPollingPolicyTest {

    @Test
    fun pollDelayStartsQuicklyThenCapsAtSixSeconds() {
        assertEquals(2_000L, ReviewPollingPolicy.nextDelayMillis(0))
        assertEquals(4_000L, ReviewPollingPolicy.nextDelayMillis(1))
        assertEquals(6_000L, ReviewPollingPolicy.nextDelayMillis(2))
        assertEquals(6_000L, ReviewPollingPolicy.nextDelayMillis(50))
    }

    @Test
    fun cadenceIsTighterThanCourseGeneration() {
        // A review is one short LLM call; course generation is two long ones.
        // Reusing the generation cadence would leave the learner idling on a
        // 4s-first / 12s-cap poll for a report that is often already done.
        assertTrue(ReviewPollingPolicy.FAST_POLL_MILLIS < GeneratePollingPolicy.FAST_POLL_MILLIS)
        assertTrue(ReviewPollingPolicy.MAX_POLL_MILLIS < GeneratePollingPolicy.MAX_POLL_MILLIS)
    }

    @Test
    fun giveUpWindowComfortablyExceedsMeasuredLlmLatency() {
        val measuredBackendLatencyMillis = 125_000L // 20s x 3 SDK tries x 2 judge rounds
        // Polls must still be in flight long after the slowest honest run finishes,
        // otherwise the learner stares at a permanent "generating" shell.
        assertTrue(ReviewPollingPolicy.TIMEOUT_MILLIS > measuredBackendLatencyMillis)
        assertFalse(ReviewPollingPolicy.isTimedOut(120_000L))
        assertTrue(ReviewPollingPolicy.isTimedOut(ReviewPollingPolicy.TIMEOUT_MILLIS))
    }

    @Test
    fun timeoutIsInPollsNotInHttpWallClock() {
        // The whole point of going async: the budget is now minutes of polling,
        // not one request that must beat a 30s socket.
        assertTrue(ReviewPollingPolicy.TIMEOUT_MILLIS > 30_000L)
    }

    @Test
    fun onlyGeneratingKeepsTheLoopRunning() {
        assertTrue(ReviewPollingPolicy.shouldKeepPolling("generating"))
        assertFalse(ReviewPollingPolicy.shouldKeepPolling("ready"))
        assertFalse(ReviewPollingPolicy.shouldKeepPolling("failed"))
        // Absent status means "nothing is being generated" (never finished, or
        // a session snapshot predating this field) - must not spin forever.
        assertFalse(ReviewPollingPolicy.shouldKeepPolling(null))
        assertFalse(ReviewPollingPolicy.shouldKeepPolling(""))
        assertFalse(ReviewPollingPolicy.shouldKeepPolling("running"))
    }

    @Test
    fun terminalIsReadyOrFailedOnly() {
        assertTrue(ReviewPollingPolicy.isTerminal("ready"))
        assertTrue(ReviewPollingPolicy.isTerminal("failed"))
        assertFalse(ReviewPollingPolicy.isTerminal("generating"))
        assertFalse(ReviewPollingPolicy.isTerminal(null))
    }

    @Test
    fun everyKnownStatusEitherPollsOrTerminatesNeverBothNeverNeither() {
        // A status that is both "keep polling" and "terminal" would loop forever;
        // one that is neither would strand the review page on a shell with no
        // report and no error. The three statuses the backend can emit must each
        // land in exactly one bucket.
        for (status in listOf("generating", "ready", "failed")) {
            val keepsPolling = ReviewPollingPolicy.shouldKeepPolling(status)
            val terminal = ReviewPollingPolicy.isTerminal(status)
            assertTrue("status=$status is in neither bucket", keepsPolling || terminal)
            assertFalse("status=$status is in both buckets", keepsPolling && terminal)
        }
    }

    @Test
    fun unknownStatusStopsPollingSoThePageShowsAnErrorNotASpinner() {
        // Absent/unrecognised status means "nothing is being generated" (never
        // finished, or a snapshot predating review_status). Spinning on it would
        // reproduce the original complaint: a review page that never resolves.
        for (status in listOf(null, "", "running", "bogus")) {
            assertFalse(ReviewPollingPolicy.shouldKeepPolling(status))
            assertFalse(ReviewPollingPolicy.isTerminal(status))
        }
    }

    @Test
    fun stageTextChangesOnlyAfterARealWait() {
        assertEquals("AI 正在写总评…", ReviewPollingPolicy.stageText(0L))
        assertNotEquals(
            ReviewPollingPolicy.stageText(0L),
            ReviewPollingPolicy.stageText(ReviewPollingPolicy.TIMEOUT_MILLIS)
        )
    }
}
