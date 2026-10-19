package com.app.english.ui.scenes

import com.app.english.domain.model.MissionTurn
import com.app.english.domain.model.MissionTurnLog
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.WordScore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * §A3 判分**回填合并**规则锁 ([applyGradingToBubbles])。
 *
 * 判分移出请求之后, 润色/语法词汇分/逐词染色都是几秒后才到的; 回填时必须只动"还在等"
 * 的那几条气泡, 其余原样返回 —— 否则重进一次页面就会把学员正在看的那一屏全部重组,
 * 而报错留下的那一轮会被别人的判分覆盖。
 */
class MissionGradingMergeTest {

    private fun userBubble(
        turnIndex: Int,
        pending: Boolean,
        translation: String? = null,
        polish: PolishBubble? = null
    ) = MissionBubble.User(
        text = "I went hiking.",
        hasTranscript = true,
        polish = polish,
        translation = translation,
        gradingPending = pending,
        turnIndex = turnIndex
    )

    private fun log(
        index: Int,
        grading: String,
        polish: PolishSuggestion? = null,
        learnerCn: String = "",
        replyCn: String = ""
    ) = MissionTurnLog(
        turnIndex = index,
        transcript = "I went hiking.",
        reply = "Nice! Which trail?",
        polish = polish,
        costsScore = false,
        replyCn = replyCn,
        learnerCn = learnerCn,
        gradingStatus = grading,
        subScores = mapOf("grammar" to 90.0, "vocabulary" to null),
        wordDetails = listOf(WordScore("hiking", 31.0, "/ˈhaɪkɪŋ/")),
        speechRateWpm = 118.0
    )

    @Test
    fun readyLogFillsPolishEvidenceAndChinese() {
        val merged = applyGradingToBubbles(
            bubbles = listOf(userBubble(turnIndex = 1, pending = true)),
            turns = listOf(
                log(
                    index = 1,
                    grading = "ready",
                    polish = PolishSuggestion("I go hiking", "I went hiking", "过去时。", "我去徒步了。"),
                    learnerCn = "我去徒步了。",
                    replyCn = "不错！哪条路线？"
                )
            )
        )
        val bubble = merged.single() as MissionBubble.User
        assertEquals("I go hiking", bubble.polish?.original)
        assertEquals("I went hiking", bubble.polish?.polished)
        assertEquals("我去徒步了。", bubble.polish?.polishedCn)
        assertEquals("我去徒步了。", bubble.translation)
        // 第三态收工: 不再挂着「评分生成中…」。
        assertFalse(bubble.gradingPending)
        // 逐词染色与语速也一起回来了 (整卡回填, 不是只填润色)。
        assertEquals(listOf("hiking"), bubble.speech?.weakWords)
        assertEquals("语速 118 词/分", bubble.speech?.rateLabel)
    }

    @Test
    fun failedLogIsSilentlyOmittedNotReported() {
        val merged = applyGradingToBubbles(
            bubbles = listOf(userBubble(turnIndex = 2, pending = true)),
            turns = listOf(log(index = 2, grading = "failed"))
        )
        val bubble = merged.single() as MissionBubble.User
        // 判分失败 = 这一轮没有润色, 不是"这一轮不存在": 气泡还在, 只是那一行不存在,
        // 也没有任何「评分失败」的文案冒出来 (界面上就一个 null)。
        assertNull(bubble.polish)
        assertFalse(bubble.gradingPending)
        assertEquals("I went hiking.", bubble.text)
    }

    @Test
    fun stillPendingKeepsTheWaitingRowForAnotherRound() {
        val merged = applyGradingToBubbles(
            bubbles = listOf(userBubble(turnIndex = 3, pending = true)),
            turns = listOf(log(index = 3, grading = "pending"))
        )
        assertTrue((merged.single() as MissionBubble.User).gradingPending)
    }

    @Test
    fun settledBubblesAndFailedRoundsAreLeftUntouched() {
        // 已经落定的轮次再合一次没有意义; 报错留下的那一轮 (turnIndex 可能与重试成功的
        // 那一轮相同, 但 gradingPending 恒 false) 更不该被别人的判分覆盖。
        val settled = userBubble(
            turnIndex = 4,
            pending = false,
            translation = "原来的中文",
            polish = PolishBubble("a", "b", "c", "d")
        )
        val failedRound = userBubble(turnIndex = 5, pending = false)
        val ai = MissionBubble.Ai(text = "Nice! Which trail?", turnIndex = 4, translation = "哪条")
        val merged = applyGradingToBubbles(
            bubbles = listOf(settled, failedRound, ai),
            turns = listOf(
                log(
                    index = 4,
                    grading = "ready",
                    polish = PolishSuggestion("x", "y", "z", "w"),
                    learnerCn = "被下一条判分借用的中文"
                ),
                log(index = 5, grading = "ready")
            )
        )
        assertEquals(listOf(settled, failedRound, ai), merged)
    }

    @Test
    fun emptyTurnsLeaveBubblesAlone() {
        val bubbles = listOf(userBubble(turnIndex = 1, pending = true))
        assertEquals(bubbles, applyGradingToBubbles(bubbles, emptyList()))
    }

    @Test
    fun speechStripHasOneImplementationForLiveTurnsAndRestoredLogs() {
        // 实时一轮与恢复/回填快照必须画出同一张条, 所以两个入口共用一个实现 ——
        // 这条锁住"它们不会各漂一份"。
        val turn = MissionTurn(
            turnIndex = 1,
            transcript = "I went hiking.",
            reply = "Nice!",
            suggestion = "",
            subScores = mapOf("pronunciation" to 66.0, "grammar" to null),
            wordDetails = listOf(WordScore("hiking", 31.0, "/ˈhaɪkɪŋ/")),
            speechRateWpm = 118.0
        )
        assertEquals(
            speechStripOf(turn),
            speechStripOf(turn.subScores, turn.wordDetails, turn.speechRateWpm)
        )
        // 三个来源全空 -> null (纯文本轮没有发音证据, 硬画一条空杠就是撒谎)。
        assertNull(speechStripOf(emptyMap(), emptyList(), null))
    }
}
