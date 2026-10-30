package com.app.english.ui.chat

import com.app.english.domain.model.ChatBubbleKind
import com.app.english.domain.model.ChatGrade
import com.app.english.domain.model.ChatMessage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 聊天界面纯逻辑的锁。
 *
 * 本仓没有 Compose UI 测试底座, 所以"点语音条出文字""缺轴不渲染""有 pending 无 url
 * 不许报错"这类契约只要写在 composable 里, 就只能等真机走查才发现 —— 而真机走查是这个
 * 盒子上永远排不上的那件事。把决策抽成纯函数之后, 它们第一次变得可测。
 */
class ChatUiModelTest {

    // ---------------------------------------------------------- 语音条外观

    @Test
    fun `voice bar label rounds to whole seconds and switches format past a minute`() {
        assertEquals("3″", voiceBarLabel(2880))
        assertEquals("1″", voiceBarLabel(1000))
        assertEquals("", voiceBarLabel(0))
        // 没合成出来时不许显示 "0″" —— 那会让一个待补的语音条看起来像一段空录音。
        assertEquals("", voiceBarLabel(-5))
        assertEquals("1:05", voiceBarLabel(65_000))
    }

    @Test
    fun `voice bar bar count grows with duration but stays bounded`() {
        assertTrue(voiceBarBars(0) in 3..14)
        assertTrue(voiceBarBars(600) >= 3)
        assertTrue(voiceBarBars(3_600_000) <= 14)
        assertTrue(voiceBarBars(9_000) > voiceBarBars(2_000))
    }

    // ------------------------------------------------- 降级: 待补音频不是错误

    @Test
    fun `pending audio without url is a fallback request, never an error`() {
        val line = ChatMessage(
            id = "m1",
            kind = ChatBubbleKind.LINE,
            roleId = "r1",
            text = "What would you like?",
            audioUrl = null,
            audioPending = true
        )
        assertFalse("没 URL 就没有可播的东西", hasPlayableAudio(line))
        assertTrue("但这是降级, 该按需补合成", needsTtsFallback(line))
    }

    @Test
    fun `hint and grade bubbles never ask for tts even when marked pending`() {
        // 只有角色台词有语音条; 建议与点评是纯文本。
        val hint =
            ChatMessage(
                id = "h1",
                kind = ChatBubbleKind.HINT,
                text = "I'll have noodles",
                audioPending = true
            )
        assertFalse(needsTtsFallback(hint))
        val user =
            ChatMessage(
                id = "u1",
                kind = ChatBubbleKind.USER,
                recognizedText = "我要面",
                audioPending = true
            )
        assertFalse(needsTtsFallback(user))
    }

    @Test
    fun `a line with audio already present needs no fallback`() {
        val line = ChatMessage(
            id = "m1",
            kind = ChatBubbleKind.LINE,
            text = "Hi",
            audioUrl = "http://h/static/tts/a.wav",
            audioPending = false
        )
        assertTrue(hasPlayableAudio(line))
        assertFalse(needsTtsFallback(line))
    }

    // ---------------------------------------------------------- 长按翻译分派

    @Test
    fun `bubbles that already carry both languages toggle locally without a request`() {
        val line = ChatMessage(
            id = "m1",
            kind = ChatBubbleKind.LINE,
            text = "What would you like?",
            textCn = "你想要点什么?"
        )
        val plan = translationPlan(line, showingCn = false)
        assertTrue("自带对照就该本地切: $plan", plan is TranslationPlan.LocalToggle)
        assertEquals(LANG_ZH, (plan as TranslationPlan.LocalToggle).targetLang)
        val back = translationPlan(line, showingCn = true)
        assertEquals(LANG_EN, (back as TranslationPlan.LocalToggle).targetLang)
    }

    @Test
    fun `the learner's own chinese sentence is the one that needs a real translation`() {
        val user = ChatMessage(
            id = "u1",
            kind = ChatBubbleKind.USER,
            recognizedText = "我想要牛肉面",
            spoke = LANG_ZH
        )
        val plan = translationPlan(user)
        assertTrue(plan is TranslationPlan.Remote)
        plan as TranslationPlan.Remote
        assertEquals("我想要牛肉面", plan.text)
        assertEquals("中文那句要翻成英文", LANG_EN, plan.targetLang)
    }

    @Test
    fun `an english sentence from the learner translates the other way`() {
        val user =
            ChatMessage(
                id = "u1",
                kind = ChatBubbleKind.USER,
                recognizedText = "I want beef noodles"
            )
        assertEquals(LANG_ZH, (translationPlan(user) as TranslationPlan.Remote).targetLang)
    }

    @Test
    fun `a line with only one language present falls back to a real translation`() {
        val englishOnly = ChatMessage(id = "m1", kind = ChatBubbleKind.LINE, text = "Any plans?")
        assertTrue(translationPlan(englishOnly) is TranslationPlan.Remote)
        assertEquals(LANG_ZH, (translationPlan(englishOnly) as TranslationPlan.Remote).targetLang)
    }

    @Test
    fun `empty bubbles and grade cards offer nothing to translate`() {
        assertTrue(
            translationPlan(
                ChatMessage(id = "u", kind = ChatBubbleKind.USER)
            ) is TranslationPlan.Nothing
        )
        assertTrue(
            translationPlan(
                ChatMessage(id = "g", kind = ChatBubbleKind.GRADE)
            ) is TranslationPlan.Nothing
        )
    }

    // ------------------------------------------------------------ 评分卡渲染

    @Test
    fun `pending grade renders a placeholder with no numbers`() {
        val render = gradeRender(ChatGrade(status = "pending"))
        assertTrue(render.visible)
        assertTrue(render.pending)
        assertEquals("", render.scoreLabel)
        assertTrue(render.axes.isEmpty())
    }

    @Test
    fun `failed grade renders nothing at all`() {
        // 点评没有 != 这一轮不存在: 其它气泡一颗都不能少, 但这颗安静地消失。
        assertFalse(gradeRender(ChatGrade(status = "failed")).visible)
    }

    @Test
    fun `missing axes are not rendered, especially not as zero`() {
        // 学员说中文的那一轮没有发音证据。画 "发音 0" 等于把"没测"说成"测了且很差"。
        val render = gradeRender(
            ChatGrade(
                status = "ready",
                score = 78,
                axes = mapOf("relevance" to 90.0, "informativeness" to 66.0)
            )
        )
        assertTrue(render.visible)
        val labels = render.axes.map { it.first }
        assertFalse("没有证据的轴不许出现", labels.contains("发音"))
        assertFalse("连 0 都不许出现 (0 = 测了且很差)", labels.contains("推进"))
        assertEquals(listOf("切题" to 90, "信息" to 66), render.axes)
    }

    @Test
    fun `pronunciation shows up only when the learner actually spoke english`() {
        val render = gradeRender(
            ChatGrade(
                status = "ready",
                score = 80,
                axes = mapOf(
                    "relevance" to 80.0,
                    "informativeness" to 80.0,
                    "appropriateness" to 80.0,
                    "beat_progress" to 1.0,
                    "pronunciation" to 74.0
                )
            )
        )
        assertTrue(render.axes.any { it.first == "发音" })
        assertEquals(74, render.axes.first { it.first == "发音" }.second)
    }

    @Test
    fun `missing comment falls back to the english one rather than an empty line`() {
        val render = gradeRender(ChatGrade(status = "ready", score = 60, comment = "Good try."))
        assertEquals("Good try.", render.comment)
    }

    // ------------------------------------------------------------ 列表合并

    @Test
    fun `bubble keys are the server ids and stay unique`() {
        // v2.3.0 那次实战页用**内容**当 LazyColumn 的 key, 撞了重复 key 崩溃 (6fae05d)。
        // 失败也落气泡、同一句被两个角色说、回填把一颗气泡改回原样 —— 都会造出内容相等的两行。
        val sameText = listOf(
            ChatMessage(id = "m1", kind = ChatBubbleKind.LINE, text = "Hi"),
            ChatMessage(id = "m2", kind = ChatBubbleKind.LINE, text = "Hi")
        )
        assertEquals(2, sameText.map { bubbleKey(it) }.toSet().size)
    }

    @Test
    fun `appending a turn never duplicates an id already on screen`() {
        val existing = listOf(
            ChatMessage(id = "u1", kind = ChatBubbleKind.USER, text = "x"),
            ChatMessage(
                id = "g1",
                kind = ChatBubbleKind.GRADE,
                grade = ChatGrade(status = "pending")
            )
        )
        val appended = listOf(
            ChatMessage(
                id = "g1",
                kind = ChatBubbleKind.GRADE,
                grade = ChatGrade(status = "ready", score = 70)
            ),
            ChatMessage(id = "m3", kind = ChatBubbleKind.LINE, text = "Nice")
        )
        val merged = mergeAppended(existing, appended)
        assertEquals(listOf("u1", "g1", "m3"), merged.map { it.id })
    }

    @Test
    fun `a full re-read upgrades in place instead of appending a second card`() {
        val existing = listOf(
            ChatMessage(id = "u1", kind = ChatBubbleKind.USER, text = "x"),
            ChatMessage(
                id = "g1",
                kind = ChatBubbleKind.GRADE,
                grade = ChatGrade(status = "pending")
            )
        )
        val snapshot = listOf(
            ChatMessage(id = "u1", kind = ChatBubbleKind.USER, text = "x"),
            ChatMessage(
                id = "g1",
                kind = ChatBubbleKind.GRADE,
                grade = ChatGrade(status = "ready", score = 82)
            )
        )
        val merged = mergeSnapshot(existing, snapshot)
        assertEquals(2, merged.size)
        assertEquals(82, merged.last().grade?.score)
    }

    @Test
    fun `polling continues while any grade is pending and stops once none is`() {
        assertTrue(
            anyGradePending(
                listOf(
                    ChatMessage(
                        id = "g",
                        kind = ChatBubbleKind.GRADE,
                        grade = ChatGrade(status = "pending")
                    )
                )
            )
        )
        assertFalse(
            anyGradePending(
                listOf(
                    ChatMessage(
                        id = "g",
                        kind = ChatBubbleKind.GRADE,
                        grade = ChatGrade(status = "ready")
                    )
                )
            )
        )
        assertFalse(anyGradePending(emptyList()))
    }

    @Test
    fun `failed grades keep the polling gate open so they can still recover`() {
        // 过一轮水位还能翻成 ready: 一次 LLM 抖动不该永久吃掉这轮的点评。
        assertTrue(GradingPollCadence.shouldKeepPolling(ChatGrade.GRADE_PENDING))
        assertTrue(GradingPollCadence.shouldKeepPolling(ChatGrade.GRADE_FAILED))
        assertFalse(GradingPollCadence.shouldKeepPolling(ChatGrade.GRADE_READY))
        assertFalse(GradingPollCadence.shouldKeepPolling(""))
    }

    @Test
    fun `poll backoff is capped and failures eventually give up`() {
        var delay = GradingPollCadence.FAST_MILLIS
        repeat(8) { delay = GradingPollCadence.nextDelayMillis(delay) }
        assertEquals(GradingPollCadence.MAX_MILLIS, delay)
        assertFalse(GradingPollCadence.shouldGiveUp(GradingPollCadence.MAX_FAILURES - 1))
        assertTrue(GradingPollCadence.shouldGiveUp(GradingPollCadence.MAX_FAILURES))
    }

    // ------------------------------------------------------ 本机录音回听

    @Test
    fun `own voice plays the local file and never falls back to tts`() {
        val taken = mapOf(
            "take-1.wav" to "file:///data/user/0/com.app.english/files/recordings/chat/take-1.wav"
        )
        val mine =
            ChatMessage(
                id = "u1",
                kind = ChatBubbleKind.USER,
                recognizedText = "我要面",
                localRecording = "take-1.wav"
            )
        assertEquals(taken.getValue("take-1.wav"), localRecordingPath(mine, taken))

        // 查不到就不播。绝不许拿 TTS 合成一段冒充"你刚才说的话"。
        assertNull(localRecordingPath(mine, emptyMap()))
        assertNull(
            localRecordingPath(
                ChatMessage(id = "u2", kind = ChatBubbleKind.USER, text = "打的字"),
                taken
            )
        )
    }
}
