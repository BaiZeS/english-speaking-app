package com.app.english.ui.scenes

import com.app.english.domain.model.MissionTurnLog
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.WordScore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 气泡身份的锁 (审查 C1)。
 *
 * 崩溃的形状很具体: 「失败也落气泡」之后, 语音发送连挂两次会落下两条逐字节相同的
 * `User("", hasTranscript=false, turnIndex=X)`; 而 LazyColumn 的 key 当时是
 * `class-turnIndex-hashCode` —— 内容一样, key 就一样, 组合当场抛
 * `IllegalArgumentException`。修法只改 key 的来源 (单调 id), 所以这里锁两件事:
 *
 * 1. 内容相同的失败气泡**不再**算出同一个 key;
 * 2. 判分回填 (copy) 不改 id —— 否则每次刷新都换 key, 那一项的组合状态 (「译」的展开态)
 *    会被丢掉重算 (审查 M6)。
 */
class MissionBubbleIdentityTest {

    /** 一条"语音发送失败"落下的气泡: 转写没回来, 所以内容全是空。 */
    private fun failedRound(id: Long) = MissionBubble.User(
        text = "",
        hasTranscript = false,
        polish = null,
        turnIndex = 3,
        id = id
    )

    /** 旧的 key 方案, 留着证明"为什么当初会崩": 它只看得见内容。 */
    private fun legacyKey(bubble: MissionBubble): String =
        "${bubble.javaClass.simpleName}-${bubble.turnIndex}-${bubble.hashCode()}"

    @Test
    fun duplicateFailedRoundsWouldHaveCollidedOnContentKeys() {
        // 连挂两次 = 两条一模一样的气泡 (id 还没发, 都是默认 0)。
        val first = failedRound(id = 0L)
        val second = failedRound(id = 0L)
        assertEquals(first, second)
        assertEquals(legacyKey(first), legacyKey(second))
    }

    @Test
    fun duplicateFailedRoundsGetDistinctIdsInstead() {
        val ids = MissionBubbleIds()
        val first = failedRound(ids.next())
        val second = failedRound(ids.next())
        assertNotEquals(first.id, second.id)
        // 内容仍然一样 (这是事实, 不该改), 但数据类也分得开了 —— key 的唯一性不再靠内容。
        assertNotEquals(first, second)
        assertEquals(
            first.copy(id = second.id).text,
            second.text
        )
    }

    @Test
    fun idsAreMonotonicAndNeverReused() {
        val ids = MissionBubbleIds()
        val issued = (1..8).map { ids.next() }
        assertEquals(issued.sorted(), issued)
        assertEquals(issued.size, issued.distinct().size)
        assertTrue(issued.all { it > 0L })
    }

    @Test
    fun gradingMergeKeepsBubbleIdSoExpansionStateSurvives() {
        val bubble = MissionBubble.User(
            text = "I went hiking.",
            hasTranscript = true,
            polish = null,
            translation = null,
            gradingPending = true,
            turnIndex = 1,
            id = 7L
        )
        val merged = applyGradingToBubbles(
            bubbles = listOf(bubble),
            turns = listOf(
                MissionTurnLog(
                    turnIndex = 1,
                    transcript = "I went hiking.",
                    reply = "Nice!",
                    polish = PolishSuggestion("I go hiking", "I went hiking", "过去时。", "我去徒步了。"),
                    costsScore = false,
                    learnerCn = "我去徒步了。",
                    gradingStatus = "ready",
                    subScores = mapOf("grammar" to 90.0),
                    wordDetails = listOf(WordScore("hiking", 31.0, "/ˈhaɪkɪŋ/")),
                    speechRateWpm = 118.0
                )
            )
        )
        val filled = merged.single() as MissionBubble.User
        assertEquals(7L, filled.id)
        assertEquals("我去徒步了。", filled.polish?.polishedCn)
    }
}
