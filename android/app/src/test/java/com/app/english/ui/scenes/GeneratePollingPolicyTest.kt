package com.app.english.ui.scenes

import com.app.english.domain.model.GenerationJob
import com.app.english.domain.model.PolishSuggestion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 生成课轮询节奏(T5 实测分钟级)与润色气泡数据映射的纯函数锁(T7 质量门)。
 */
class GeneratePollingPolicyTest {
    @Test
    fun pollDelayGrowsFastThenCapsAtTwelveSeconds() {
        assertEquals(4_000L, GeneratePollingPolicy.nextDelayMillis(0))
        assertEquals(8_000L, GeneratePollingPolicy.nextDelayMillis(1))
        assertEquals(12_000L, GeneratePollingPolicy.nextDelayMillis(2))
        assertEquals(12_000L, GeneratePollingPolicy.nextDelayMillis(10))
    }

    @Test
    fun timeoutOnlyAfterFifteenMinutes() {
        assertFalse(GeneratePollingPolicy.isTimedOut(14 * 60_000L))
        assertTrue(GeneratePollingPolicy.isTimedOut(15 * 60_000L))
        assertTrue(GeneratePollingPolicy.isTimedOut(16 * 60_000L))
    }

    @Test
    fun stageIndexFollowsBackendProgress() {
        assertEquals(0, GeneratePollingPolicy.stageIndex(0.05))
        assertEquals(1, GeneratePollingPolicy.stageIndex(0.55))
        assertEquals(2, GeneratePollingPolicy.stageIndex(0.9))
    }

    @Test
    fun terminalMeansReadyOrFailed() {
        assertTrue(
            GeneratePollingPolicy.isTerminal(
                GenerationJob("j", "ready", 1.0, "生成完成", "scene_x", null)
            )
        )
        assertTrue(
            GeneratePollingPolicy.isTerminal(
                GenerationJob("j", "failed", 0.4, "", null, "llm bad json")
            )
        )
        assertFalse(
            GeneratePollingPolicy.isTerminal(
                GenerationJob("j", "running", 0.05, "理解学习目标…", null, null)
            )
        )
    }
}

class PolishBubbleMappingTest {
    @Test
    fun nullPolishYieldsNoBubble() {
        assertNull((null as PolishSuggestion?).toBubbleOrNull())
    }

    @Test
    fun blankPolishedYieldsNoBubble() {
        val polish = PolishSuggestion(original = "hello", polished = "  ", explanationCn = "")
        assertNull(polish.toBubbleOrNull())
    }

    @Test
    fun identicalPolishYieldsNoBubble() {
        val polish =
            PolishSuggestion(original = "How much?", polished = "How much?", explanationCn = "ok")
        assertNull(polish.toBubbleOrNull())
    }

    @Test
    fun realPolishRendersTheContrastCard() {
        // 2026-09-05 本机起服真实样本: translate 步的误译润色。
        val polish = PolishSuggestion(
            original = "Can I have a croissant?",
            polished = "Can I change that to a large?",
            explanationCn = "原句是询问换成大杯，不是点羊角面包。"
        )
        val bubble = polish.toBubbleOrNull()
        assertNotNull(bubble)
        assertTrue(bubble!!.isOriginalWorse)
        assertEquals("Can I change that to a large?", bubble.polished)
    }

    @Test
    fun taskProgressLabelCountsDoneOverTotal() {
        val checklist = listOf(
            com.app.english.domain.model.TaskChip("t1", "点单", "", true, true, "ok"),
            com.app.english.domain.model.TaskChip("t2", "问价", "", true, false, ""),
            com.app.english.domain.model.TaskChip("t3", "收尾", "", false, true, "")
        )
        assertEquals("2/3", taskProgressLabel(checklist))
    }
}
