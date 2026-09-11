package com.app.english.ui.scenes

import com.app.english.domain.model.DrillGradeResult
import com.app.english.domain.model.MissionTurn
import com.app.english.domain.model.WordScore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 共用维度读数表的行为锁 —— 打基础逐题反馈与实战逐轮发音条都读它。
 *
 * 关键在两条"宁可不画也不撒谎"的规则: null 维度是"这一轮没测到", 不是 0 分; 全空的一轮
 * 干脆不出现, 免得聊天流里挂一排空杠。
 */
class SubScoreReadoutTest {
    private fun turn(
        subScores: Map<String, Double?>,
        wordDetails: List<WordScore> = emptyList(),
        speechRateWpm: Double? = null
    ) = MissionTurn(
        turnIndex = 1,
        transcript = "Can I get a medium coffee?",
        reply = "Sure.",
        suggestion = "",
        subScores = subScores,
        wordDetails = wordDetails,
        speechRateWpm = speechRateWpm
    )

    @Test
    fun dimensionsComeOutInFixedOrderAndNullsAreSkippedNotZeroed() {
        val readout = subScoreReadout(
            mapOf(
                "vocabulary" to 88.0,
                "pronunciation" to 76.5,
                "fluency" to null,
                "grammar" to null,
                "completeness" to null
            )
        )
        assertEquals(listOf("发音" to 76.5, "词汇" to 88.0), readout.map { it.label to it.score })
    }

    @Test
    fun unknownDimensionNamesAreIgnoredRatherThanGuessedAt() {
        // 后端加维度时这里宁可什么都不显示, 也不给一个没有中文标签的裸键。
        assertEquals(emptyList<SubScoreReadout>(), subScoreReadout(mapOf("confidence" to 90.0)))
    }

    @Test
    fun drillGradeAndMissionTurnShareTheSameTable() {
        val grade = DrillGradeResult(
            stepId = "f1",
            stepType = "read_along",
            score = 70.0,
            passed = true,
            passScore = 60.0,
            feedbackCn = "",
            pronunciation = 66.0,
            grammar = 90.0
        )
        assertEquals(
            drillSubScoreReadout(grade).map { it.label to it.score },
            subScoreReadout(
                mapOf("grammar" to 90.0, "pronunciation" to 66.0, "fluency" to null)
            ).map { it.label to it.score }
        )
    }

    @Test
    fun aTextOnlyTurnHasNoStripAtAllRatherThanAnEmptyOne() {
        assertNull(speechStripOf(turn(subScores = mapOf("pronunciation" to null))))
        assertNull(speechStripOf(turn(subScores = emptyMap(), speechRateWpm = 0.0)))
    }

    @Test
    fun stripKeepsEvidenceDimsRateAndTheWordsThatWentRed() {
        val strip = speechStripOf(
            turn(
                subScores = mapOf("pronunciation" to 82.0, "grammar" to null),
                wordDetails = listOf(
                    WordScore("medium", 91.0, "/ˈmiːdiəm/"),
                    WordScore("croissant", 34.0, "/kwaˈsɑ̃/"),
                    WordScore("please", 41.0, null),
                    WordScore("croissant", 22.0, null)
                ),
                speechRateWpm = 137.6
            )
        )
        assertEquals(listOf("发音" to 82.0), strip!!.dims.map { it.label to it.score })
        assertEquals("语速 137 词/分", strip.rateLabel)
        // 只有红带(<60)的词进这条, 且不重复 —— 气泡里那一行要说"该回哪儿练"。
        assertEquals(listOf("croissant", "please"), strip.weakWords)
    }
}
