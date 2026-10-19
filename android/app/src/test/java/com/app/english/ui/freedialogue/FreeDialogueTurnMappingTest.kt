package com.app.english.ui.freedialogue

import com.app.english.data.remote.DialogueMessageDto
import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P8·2c/2d 的行为锁: 自由对话的协议文本与显示文本彻底分家。
 *
 * - [turnHistory]: 用户回合只携带**识别原文或空串**; 中文占位提示
 *   ("（这句没有识别到文字）" / 后端兼容层的 "（本轮自由回答）") 绝不
 *   出现在回传给模型的 history 里。
 * - [scoringRefText]: suggestedReply 为空不拦截提交 —— 兜底最后一条
 *   assistant 台词; 两者皆空才空串 (由 /score 诚实 422)。
 * - [DialogueMessageDto]: 空串回合按原样序列化 (不被编码层丢弃/替换)。
 */
class FreeDialogueTurnMappingTest {
    private fun msg(
        text: String,
        isUser: Boolean,
        hasTranscript: Boolean = true
    ): FreeDialogueMessage = FreeDialogueMessage(
        role = if (isUser) "user" else "assistant",
        text = text,
        isUser = isUser,
        hasTranscript = hasTranscript
    )

    @Test
    fun turnHistory_carriesRecognizedTextVerbatim_andNeverUiMarkers() {
        val messages = listOf(
            msg("Can I take your order?", isUser = false),
            msg("Yes, a latte please.", isUser = true),
            // 识别失败回合: text 是诚实空串 (hasTranscript=false 只影响渲染层)。
            msg("", isUser = true, hasTranscript = false),
            msg("Sure! Anything else?", isUser = false)
        )
        val history = turnHistory(messages)
        assertEquals(
            listOf(
                DialogueMessageDto(role = "assistant", text = "Can I take your order?"),
                DialogueMessageDto(role = "user", text = "Yes, a latte please."),
                DialogueMessageDto(role = "user", text = ""),
                DialogueMessageDto(role = "assistant", text = "Sure! Anything else?")
            ),
            history
        )
        assertNoUiMarker(history)
    }

    @Test
    fun turnHistory_emptyUserText_survivesSerialization() {
        val json = Json.encodeToString(
            ListSerializer(DialogueMessageDto.serializer()),
            turnHistory(listOf(msg("", isUser = true)))
        )
        // 空串字段保留 —— 服务端结构规则依赖「末尾 user 回合存在」而非其文字。
        assertEquals("""[{"role":"user","text":""}]""", json)
    }

    @Test
    fun scoringRefText_prefersSuggestion_thenLastAssistantLine() {
        val base = FreeDialogueUiState(
            messages = listOf(
                msg("Ordering coffee is fun", isUser = true),
                msg("What would you like?", isUser = false),
                msg("A flat white.", isUser = true)
            )
        )
        assertEquals(
            "Try: I'd like ...",
            scoringRefText(base.copy(suggestedReply = "Try: I'd like ..."))
        )
        // 建议为空 -> 兜底**最后一条** assistant 台词。
        assertEquals("What would you like?", scoringRefText(base.copy(suggestedReply = "   ")))
        // 全程没有 assistant 台词才空 (交给 /score 诚实报错, 客户端不发中文占位)。
        assertEquals(
            "",
            scoringRefText(
                base.copy(suggestedReply = "", messages = listOf(msg("hi", isUser = true)))
            )
        )
    }

    @Test
    fun freeDialogueMessage_blankTranscript_untouchedByProtocol() {
        // 渲染层判定只看 hasTranscript; 协议构造 (turnHistory) 从不读它。
        val blank = msg("", isUser = true, hasTranscript = false)
        assertFalse(blank.hasTranscript)
        assertTrue(blank.text.isEmpty())
        assertEquals(listOf(DialogueMessageDto("user", "")), turnHistory(listOf(blank)))
    }

    private fun assertNoUiMarker(history: List<DialogueMessageDto>) {
        val forbidden = listOf("本轮自由回答", "没有识别到文字")
        history.forEach { turn ->
            forbidden.forEach { needle ->
                assertFalse(
                    "protocol text leaked UI marker: ${turn.text}",
                    turn.text.contains(needle)
                )
            }
        }
    }

    // ---- §A4/A5: 回给服务端的「已展示参考句」清单 ----

    private fun shown(text: String, isUser: Boolean = true): FreeDialogueMessage =
        FreeDialogueMessage(
            role = if (isUser) "user" else "assistant",
            text = "whatever",
            isUser = isUser,
            shownSuggestion = text
        )

    /**
     * 只取**最近** [SHOWN_SUGGESTIONS_LIMIT] 句: prompt 预算是有限的, 而防复写只关心
     * 最近给过什么 —— 十轮之前那句重复一遍也没有意义。
     */
    @Test
    fun shownSuggestions_keepsOnlyTheLatestEight() {
        val messages = (1..10).map { shown("Try: line $it") }
        val shown = shownSuggestions(messages)
        assertEquals(8, shown.size)
        assertEquals("Try: line 3", shown.first())
        assertEquals("Try: line 10", shown.last())
    }

    /** 同一句连着展示两轮只报一次 —— 重复项白占预算, 服务端那边也没有新信息。 */
    @Test
    fun shownSuggestions_deduplicatesRepeatedSentences() {
        val messages = listOf(
            shown("I'd like a latte."),
            shown("To go, please."),
            shown("I'd like a latte."),
            shown("Could you make it large?")
        )
        assertEquals(
            listOf("I'd like a latte.", "To go, please.", "Could you make it large?"),
            shownSuggestions(messages)
        )
    }

    /** 没有参考回答的那几轮 (卡片上是"本轮没有参考回答") 不参与, 空白同理。 */
    @Test
    fun shownSuggestions_skipsBlankAndUntranslatedTurns() {
        val messages = listOf(
            shown("", isUser = false),
            shown("   "),
            shown("A flat white, please.")
        )
        assertEquals(listOf("A flat white, please."), shownSuggestions(messages))
        assertTrue(shownSuggestions(emptyList()).isEmpty())
    }

    /**
     * 调用点的形状 (与 `stopAndSubmit` 一致): 学员开口那一刻卡片上那句也要算"已展示过",
     * 所以它必须出现在清单**末尾** —— 服务端读它说"这一句别再给了"。
     */
    @Test
    fun shownSuggestions_pendingTurnCarriesTheSentenceOnTheCard() {
        val messages = listOf(
            msg("What would you like?", isUser = false),
            shown("I'd like a latte."),
            msg("", isUser = true, hasTranscript = false)
        )
        val pending = shown("Could you make it iced?")
        val shown = shownSuggestions(messages + pending)
        assertEquals("I'd like a latte.", shown.first())
        assertEquals("Could you make it iced?", shown.last())
    }
}
