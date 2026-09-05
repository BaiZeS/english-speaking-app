package com.app.english.ui.assessment

import com.app.english.domain.model.AssessmentQuestion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 测评做题页状态机的纯 JVM 锁: 逐题前进、TRANSCRIPT_UNAVAILABLE 不丢题引导改
 * 文本、最后一题交卷即进判级、判级失败可重试 —— 与后端 assessment.py 的口径
 * 一一对应。
 */
class AssessmentFlowTest {
    private fun question(no: Int) = AssessmentQuestion(
        id = "a$no",
        no = no,
        type = if (no == 1) "read_aloud" else "open_question",
        cefrAnchor = "A2",
        cnPrompt = "题干 $no",
        displayText = "Question $no",
        translationCn = "",
        seconds = 30
    )

    private val questions = listOf(question(1), question(2), question(3))

    private fun started() = reduceAssessment(
        AssessmentFlowState(),
        AssessmentEvent.Started(questions)
    )

    @Test
    fun startsInAnsweringAtFirstQuestion() {
        val state = started()
        assertEquals(AssessmentPhase.ANSWERING, state.phase)
        assertEquals(0, state.index)
        assertEquals("1/3", state.progressLabel)
        assertFalse(state.isLast)
        assertTrue(state.canSubmitText)
    }

    @Test
    fun acceptedAnswerAdvancesToNextQuestion() {
        val state = reduceAssessment(started(), AssessmentEvent.SubmitStarted)
        assertEquals(AssessmentPhase.SUBMITTING, state.phase)
        val next = reduceAssessment(
            state,
            AssessmentEvent.AnswerAccepted(answersCount = 1)
        )
        assertEquals(AssessmentPhase.ANSWERING, next.phase)
        assertEquals(1, next.index)
        assertEquals(1, next.answeredCount)
        assertEquals("2/3", next.progressLabel)
    }

    @Test
    fun lastAcceptedAnswerStartsJudging() {
        var state = started()
        repeat(2) { turn ->
            state = reduceAssessment(
                reduceAssessment(state, AssessmentEvent.SubmitStarted),
                AssessmentEvent.AnswerAccepted(turn + 1)
            )
        }
        assertTrue(state.isLast)
        state = reduceAssessment(
            reduceAssessment(state, AssessmentEvent.SubmitStarted),
            AssessmentEvent.AnswerAccepted(3)
        )
        assertEquals("最后一题交卷 = 收卷判级开始", AssessmentPhase.JUDGING, state.phase)
        assertEquals(2, state.index)
    }

    @Test
    fun transcriptUnavailableStaysAndGuidesText() {
        val state = reduceAssessment(started(), AssessmentEvent.TranscriptUnavailable)
        assertEquals("音频没有证据就不硬收, 停在原题", AssessmentPhase.ANSWERING, state.phase)
        assertEquals(0, state.index)
        assertTrue(state.audioBlocked)
        assertNull(state.error)
    }

    @Test
    fun audioBlockedFlagClearsOnNextAcceptedAnswer() {
        val blocked = reduceAssessment(started(), AssessmentEvent.TranscriptUnavailable)
        val advanced = reduceAssessment(blocked, AssessmentEvent.AnswerAccepted(1))
        assertFalse(advanced.audioBlocked)
    }

    @Test
    fun judgingFailureReturnsToAnsweringForRetry() {
        val judging = reduceAssessment(
            started(),
            AssessmentEvent.CompleteStarted
        )
        assertEquals(AssessmentPhase.JUDGING, judging.phase)
        val failed = reduceAssessment(judging, AssessmentEvent.Failed("LLM 超时"))
        assertEquals(AssessmentPhase.ANSWERING, failed.phase)
        assertEquals("LLM 超时", failed.error)
        val shown = reduceAssessment(failed, AssessmentEvent.ErrorShown)
        assertNull(shown.error)
    }

    @Test
    fun judgedMeansDone() {
        val state = reduceAssessment(
            reduceAssessment(started(), AssessmentEvent.CompleteStarted),
            AssessmentEvent.Judged
        )
        assertEquals(AssessmentPhase.DONE, state.phase)
    }

    @Test
    fun errorCodeCopyCoversTheKnownBranches() {
        assertEquals(
            "这段语音没能转写出文字, 试试改用文本作答",
            assessmentErrorCodeText("TRANSCRIPT_UNAVAILABLE", null)
        )
        assertEquals(
            "说点什么或写一句再提交",
            assessmentErrorCodeText("ASSESSMENT_ANSWER_REQUIRED", null)
        )
        assertEquals(
            "本次测评已经交过卷了, 直接看结果吧",
            assessmentErrorCodeText("ATTEMPT_NOT_ACTIVE", null)
        )
        assertEquals("fallback 用后端 message", "网络开小差", assessmentErrorCodeText(null, "网络开小差"))
        assertEquals("没有 message 时给通用文案", "提交失败, 请重试", assessmentErrorCodeText(null, null))
    }

    @Test
    fun typeLabelsCoverTheBank() {
        assertEquals("跟读", assessmentTypeLabel("read_aloud"))
        assertEquals("复述", assessmentTypeLabel("retell"))
        assertEquals("翻译", assessmentTypeLabel("translate"))
        assertEquals("开放问答", assessmentTypeLabel("open_question"))
        assertEquals("快问快答", assessmentTypeLabel("quick_chat"))
        assertEquals("作答", assessmentTypeLabel("mystery"))
    }

    @Test
    fun estimatedMinutesMatchTheRealBank() {
        // 2026-09-05 实际题库: 7 题共 260s -> 5 分钟(计划口径)。
        val bank = (1..7).map {
            question(it).copy(
                seconds = listOf(30, 30, 45, 30, 45, 60, 20)[
                    it -
                        1
                ]
            )
        }
        assertEquals(5, estimatedAssessmentMinutes(bank))
        assertEquals("空题库至少给 1 分钟", 1, estimatedAssessmentMinutes(emptyList()))
    }

    @Test
    fun dimensionAdviceCoversNullAndBands() {
        val advice = assessmentDimensionAdvice(
            mapOf(
                "pronunciation" to null,
                "grammar" to 90.0,
                "vocabulary" to 55.0,
                "fluency" to 30.0
            )
        )
        assertEquals(listOf("发音", "语法", "词汇", "流利度"), advice.map { it.label })
        assertTrue(advice[0].adviceCn.contains("没有拿到发音分"))
        assertTrue(advice[1].adviceCn.contains("扎实"))
        assertTrue(advice[2].adviceCn.contains("别停下"))
        assertTrue(advice[3].adviceCn.contains("跟读"))
        assertEquals(null, advice[0].score)
        assertEquals(90.0, advice[1].score!!, 0.0)
    }
}
