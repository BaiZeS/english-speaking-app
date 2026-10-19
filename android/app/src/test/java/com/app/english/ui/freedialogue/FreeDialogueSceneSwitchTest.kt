package com.app.english.ui.freedialogue

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 场景切换的**最新写入者胜**锁 (审查 I4)。
 *
 * 复现的形状: 学员快速连切场景 A → B, A 的响应慢, 回来时把 B 的会话整包覆盖掉 ——
 * 屏幕上显示的是 A 的台词而选择器指着 B。`FreeDialogueViewModel.generate` 现在先
 * `cancel()` 在途的那次, 再加这道令牌; 这里锁的是令牌那一半 (真协程取消要 Android 依赖,
 * 见 [LatestRequestGate] 的说明)。
 */
class FreeDialogueSceneSwitchTest {

    @Test
    fun newerRequestInvalidatesTheOlderToken() {
        val gate = LatestRequestGate()
        val first = gate.begin()
        assertTrue("刚发起的那次当然作数", gate.isCurrent(first))

        val second = gate.begin()
        // A 的响应此刻才回来: 令牌已过期, 它不许再写 state (否则新场景被整包覆盖)。
        assertFalse(gate.isCurrent(first))
        assertTrue(gate.isCurrent(second))
    }

    @Test
    fun everyAdditionalSwitchInvalidatesAllEarlierTokens() {
        val gate = LatestRequestGate()
        val tokens = (1..5).map { gate.begin() }
        assertTrue(gate.isCurrent(tokens.last()))
        tokens.dropLast(1).forEach { stale ->
            assertFalse("连切 5 次之后, 前 4 次的响应一律作废", gate.isCurrent(stale))
        }
    }

    @Test
    fun tokensAreNeverReused() {
        val gate = LatestRequestGate()
        val tokens = (1..6).map { gate.begin() }
        assertTrue(tokens.distinct().size == tokens.size)
    }
}
