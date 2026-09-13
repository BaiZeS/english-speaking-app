package com.app.english.ui.assessment

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 判级轮询节奏的纯函数锁(照 GeneratePollingPolicy 测试的口径)。
 * 生产实锤: 免费额度限速把批量判级拖过 20s -> 服务端作业预算 120s, 客户端轮询
 * 上限 150s, 超时不是失败而是"后台仍在判"。
 */
class JudgePollingPolicyTest {

    @Test
    fun `前几次快探 之后退避到封顶`() {
        assertEquals(3_000L, JudgePollingPolicy.nextDelayMillis(0))
        assertEquals(6_000L, JudgePollingPolicy.nextDelayMillis(1))
        assertEquals(9_000L, JudgePollingPolicy.nextDelayMillis(2))
        assertEquals(9_000L, JudgePollingPolicy.nextDelayMillis(3))
        assertEquals(9_000L, JudgePollingPolicy.nextDelayMillis(30))
    }

    @Test
    fun `退避节奏能覆盖作业预算窗口而不超轮询上限太多`() {
        // 累计等待到 150s 附近: 3 + 6 + 9*k >= 150 -> k = 16, 即约 19 次轮询内收敛。
        var elapsed = 0L
        var polls = 0
        while (!JudgePollingPolicy.isTimedOut(elapsed)) {
            elapsed += JudgePollingPolicy.nextDelayMillis(polls++)
        }
        assertTrue("应在 ~20 次内判超时 (实际 $polls 次)", polls in 16..20)
        assertTrue(elapsed < JudgePollingPolicy.TIMEOUT_MILLIS + JudgePollingPolicy.MAX_POLL_MILLIS)
    }

    @Test
    fun `未超时与已超时的判定`() {
        assertFalse(JudgePollingPolicy.isTimedOut(0L))
        assertFalse(JudgePollingPolicy.isTimedOut(JudgePollingPolicy.TIMEOUT_MILLIS - 1))
        assertTrue(JudgePollingPolicy.isTimedOut(JudgePollingPolicy.TIMEOUT_MILLIS))
    }
}
