package com.app.english.ui.scenes

import com.app.english.domain.model.DrillGradeResult
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 反馈"显示什么"的读数锁(与 `BriefingFeedbackTest` 的"什么时候消失"相对)。
 *
 * 这两条各自对应一个把数据说假的画法: 五维里的 null 被补成 0(＝白扣一个没发生的分),
 * 以及进度点拿着服务端给的 bestScore/lastScore/attempts 却只画一个序号。
 */
class BriefingFeedbackReadoutTest {
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
}
