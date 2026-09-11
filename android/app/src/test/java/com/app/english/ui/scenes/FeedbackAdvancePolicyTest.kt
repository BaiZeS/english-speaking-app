package com.app.english.ui.scenes

import com.app.english.domain.ScoreColorMapper
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 自动前进节奏锁(问题 4 的另一半: 反馈要给全, 但也得有人替学员翻篇)。
 *
 * 这里最要紧的一条是**阈值 85 不是 60** —— 通过线之上、优秀线之下正是唯一需要
 * 读完中文建议再动手的分数带, 在那儿自动前进会把反馈抽走。测试同时把 85 钉在
 * 既有绿线 [ScoreColorMapper.GREEN_THRESHOLD] 上: 这两处一旦各自漂移, 界面就会出现
 * "绿色但手动"或"黄色但自动"这种自相矛盾。
 */
class FeedbackAdvancePolicyTest {

    @Test
    fun autoAdvanceLineIsTheExistingExcellenceLineNotThePassLine() {
        assertEquals(
            ScoreColorMapper.GREEN_THRESHOLD,
            FeedbackAdvancePolicy.AUTO_ADVANCE_SCORE,
            0.0
        )
        assertTrue(
            "阈值必须高于 60 分通过线, 否则 60-84 分的学员读不到建议",
            FeedbackAdvancePolicy.AUTO_ADVANCE_SCORE > 60.0
        )
    }

    @Test
    fun justBelowTheLineStaysManual() {
        assertFalse(FeedbackAdvancePolicy.shouldAutoAdvance(score = 84.9, passed = true))
        assertFalse(FeedbackAdvancePolicy.shouldAutoAdvance(score = 60.0, passed = true))
        assertNull(FeedbackAdvancePolicy.armSeconds(score = 84.9, passed = true))
    }

    @Test
    fun exactlyOnTheLineArmsTheCountdown() {
        assertTrue(FeedbackAdvancePolicy.shouldAutoAdvance(score = 85.0, passed = true))
        assertEquals(
            FeedbackAdvancePolicy.countdownSeconds(),
            FeedbackAdvancePolicy.armSeconds(score = 85.0, passed = true)
        )
        assertTrue(FeedbackAdvancePolicy.shouldAutoAdvance(score = 100.0, passed = true))
    }

    @Test
    fun aFailedTakeNeverAdvancesNoMatterHowHighTheNumberLooks() {
        // passed 是服务端门禁的真值。高分但没过(pass_score 被课程抬高)也必须手动。
        assertFalse(FeedbackAdvancePolicy.shouldAutoAdvance(score = 99.0, passed = false))
        assertNull(FeedbackAdvancePolicy.armSeconds(score = 99.0, passed = false))
    }

    @Test
    fun dwellIsFiveSeconds() {
        assertEquals(5_000L, FeedbackAdvancePolicy.AUTO_ADVANCE_DELAY_MILLIS)
        assertEquals(5, FeedbackAdvancePolicy.countdownSeconds())
    }

    @Test
    fun countdownWalksExactlyToTheConfiguredDelayAndThenExpires() {
        var seconds = FeedbackAdvancePolicy.armSeconds(score = 92.0, passed = true)
        var ticks = 0
        while (!FeedbackAdvancePolicy.isFinished(seconds) && ticks < TICK_GUARD) {
            seconds = FeedbackAdvancePolicy.remainingSeconds(seconds)
            ticks++
        }
        assertTrue("秒针走不到 0, 倒计时就永远不会翻篇", FeedbackAdvancePolicy.isFinished(seconds))
        assertEquals(
            "秒针格数 × 每格时长必须等于停留时长, 不然提示会和实际翻篇时刻不一致",
            FeedbackAdvancePolicy.AUTO_ADVANCE_DELAY_MILLIS,
            ticks * FeedbackAdvancePolicy.TICK_MILLIS
        )
    }

    @Test
    fun remainingSecondsNeverGoesNegativeAndNeverRevivesACancelledCountdown() {
        assertEquals(4, FeedbackAdvancePolicy.remainingSeconds(5))
        assertEquals(0, FeedbackAdvancePolicy.remainingSeconds(1))
        assertEquals(0, FeedbackAdvancePolicy.remainingSeconds(0))
        assertNull(FeedbackAdvancePolicy.remainingSeconds(null))
    }

    @Test
    fun finishedMeansZeroLeftAndNotNullLeft() {
        // "没在倒计时"(取消/未达线)不是"走完了": 前者要把反馈留着手动继续。
        assertTrue(FeedbackAdvancePolicy.isFinished(0))
        assertFalse(FeedbackAdvancePolicy.isFinished(1))
        assertFalse(FeedbackAdvancePolicy.isFinished(null))
    }

    @Test
    fun hintCountsDownAndDisappearsWhenManual() {
        assertEquals("5 秒后自动继续 · 点按可停留", FeedbackAdvancePolicy.hintLabel(5))
        assertEquals("1 秒后自动继续 · 点按可停留", FeedbackAdvancePolicy.hintLabel(1))
        assertEquals("", FeedbackAdvancePolicy.hintLabel(null))
        assertEquals("", FeedbackAdvancePolicy.hintLabel(0))
    }
}

/** 防呆上限: 万一哪天秒针走不到 0, 让测试失败而不是挂住。 */
private const val TICK_GUARD = 100
