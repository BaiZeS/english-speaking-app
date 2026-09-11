package com.app.english.ui.score

import com.app.english.domain.model.WordScore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 成绩持久化的往返锁(E5)。
 *
 * 成绩页读的是客户端聚合, 里面**既有逐词分数又有 LLM 建议**, 后者在 `history` 表里根本
 * 没有对应列 —— 所以唯一的还原路径就是本地这份 JSON。测试只验一件事: 存进去的和读出来的
 * 必须一字不差, 而坏文件必须静默退回"没有缓存"而不是把成绩页炸掉。
 *
 * 最后那条体积断言是给"为什么不用 SharedPreferences"留的证据: 一课几十句、每句十几个词,
 * 这个 blob 是 KB 级, 塞进每次启动全量读写的 prefs XML 里是错的。
 */
class ScoreSessionCodecTest {
    private fun wordScore(word: String, score: Double, ipa: String? = null) =
        WordScore(word = word, score = score, ipa = ipa)

    private fun session(lines: List<LineScoreResult>, suggestion: String?) = ScoreSession(
        lessonTitle = "Lesson 12 · Good or bad?",
        roleName = "Teacher",
        totalScore = 78.5,
        pronunciation = 81.0,
        fluency = 72.25,
        completeness = 69.0,
        suggestion = suggestion,
        lineCount = lines.size,
        lineResults = lines,
        source = "xunfei"
    )

    private val twoLines = listOf(
        LineScoreResult(
            lineId = "L1-A1",
            text = "Good morning, everyone.",
            total = 88.0,
            wordScores = listOf(
                wordScore("good", 95.0, "/ɡʊd/"),
                wordScore("morning", 82.5, null),
                wordScore("everyone", 41.0, "/ˈevriwʌn/")
            )
        ),
        LineScoreResult(
            lineId = "L1-A2",
            text = "Let us begin.",
            total = 55.0,
            wordScores = emptyList()
        )
    )

    @Test
    fun roundTripKeepsEveryLineWordAndIpa() {
        val original = session(twoLines, "注意 morning 的尾音不要用中文的声调收尾。")
        val restored = ScoreSessionCodec.decode(ScoreSessionCodec.encode(original))

        assertNotNull(restored)
        assertEquals(original, restored)
        assertEquals(2, restored!!.lineResults.size)
        assertEquals(3, restored.lineResults.first().wordScores.size)
        assertEquals("/ɡʊd/", restored.lineResults.first().wordScores.first().ipa)
        // 没有音标的词不能被补成空串: 界面用 null 决定"这一行不画音标"。
        assertNull(restored.lineResults.first().wordScores[1].ipa)
        assertEquals(55.0, restored.lineResults.last().total, 0.001)
    }

    @Test
    fun aMissingSuggestionStaysMissingInsteadOfBecomingAnEmptyLine() {
        val original = session(twoLines, suggestion = null)
        val restored = ScoreSessionCodec.decode(ScoreSessionCodec.encode(original))
        assertNull(restored!!.suggestion)
    }

    @Test
    fun theStubFlagSurvivesSoTheWarningStillShowsAfterARestart() {
        // source 丢了, 占位假分的警示就跟着丢了 —— 重启后成绩页会安静地谎称这是真评测。
        val stub = session(twoLines, "多练连读。").copy(source = "stub")
        val restored = ScoreSessionCodec.decode(ScoreSessionCodec.encode(stub))
        assertEquals("stub", restored!!.source)
        assertTrue(restored.isStub)
    }

    @Test
    fun corruptOrMissingPayloadsDecodeToNoCacheRatherThanThrow() {
        assertNull(ScoreSessionCodec.decode(null))
        assertNull(ScoreSessionCodec.decode(""))
        assertNull(ScoreSessionCodec.decode("   "))
        assertNull(ScoreSessionCodec.decode("not json at all"))
        // 被杀在写一半的 JSON: 结构不完整 -> 退回"没有缓存"。
        assertNull(
            ScoreSessionCodec.decode(
                """{"lessonTitle":"x","lineResults":[{"lineId":"L1","text":"a"""
            )
        )
    }

    @Test
    fun anUnknownFieldFromANewerBuildIsIgnored() {
        // 降级安装(新包多写了字段、旧包读到)不能让成绩页白屏。
        val persisted = ScoreSessionCodec.encode(session(twoLines, "建议"))
            .removeSuffix("}")
            .plus(""","futureThing":42}""")
        val restored = ScoreSessionCodec.decode(persisted)
        assertNotNull(restored)
        assertEquals(78.5, restored!!.totalScore, 0.001)
        assertEquals(twoLines, restored.lineResults)
    }

    @Test
    fun aFullLessonBlobIsKbScaleSoItBelongsToAFileNotToPreferences() {
        val lines = (1..40).map { index ->
            LineScoreResult(
                lineId = "L$index",
                text = "This is sentence number $index of the lesson we are reading today.",
                total = 60.0 + index % 40,
                wordScores = (1..12).map { word ->
                    wordScore("word${word}_of_$index", 50.0 + word, "/wɜːd/")
                }
            )
        }
        val json = ScoreSessionCodec.encode(session(lines, "把每句话的尾音降下来。"))
        assertTrue(
            "整课逐词分是 KB 量级(实测 ${json.length} 字符), 这正是它不能进 prefs 的理由",
            json.length > 8_000
        )
        assertEquals(lines.size, ScoreSessionCodec.decode(json)!!.lineResults.size)
    }
}
