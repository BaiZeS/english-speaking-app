package com.app.english.ui.scenes

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * §A3 判分回填的**去留判据**锁。
 *
 * 三条判据各自对应一次会被写错的地方 (见 [GradingPollingPolicy] 的说明): `failed` 不是
 * 终点、脏值不许当 `pending`、第一个请求超时不算"服务端说不用等"。
 */
class GradingPollingPolicyTest {

    // ---- 界面那一行该不该出现 ----

    @Test
    fun onlyTheLiteralPendingRendersTheWaitingRow() {
        assertTrue(GradingPollingPolicy.isPending(GradingPollingPolicy.STATUS_PENDING))
        // 判分失败**不是**"评分生成中": 那一行静默缺省, 绝不弹「评分失败」。
        assertFalse(GradingPollingPolicy.isPending(GradingPollingPolicy.STATUS_FAILED))
        assertFalse(GradingPollingPolicy.isPending(GradingPollingPolicy.STATUS_READY))
        assertFalse(GradingPollingPolicy.isPending(null))
        assertFalse(GradingPollingPolicy.isPending(""))
        // JSON 列里的脏值/大小写变体一律不当 pending 用。
        assertFalse(GradingPollingPolicy.isPending("PENDING"))
        assertFalse(GradingPollingPolicy.isPending("running"))
    }

    @Test
    fun failedStillCountsAsSomethingToWaitFor() {
        // 后端契约点名要求: `failed` 过一轮水位会被就地重派, 可能翻身成 `ready` ——
        // 所以会话级"还有没有要等的"必须把 failed 也算上, 否则页面收工太早。
        assertTrue(GradingPollingPolicy.isAwaiting(GradingPollingPolicy.STATUS_FAILED))
        assertTrue(GradingPollingPolicy.isAwaiting(GradingPollingPolicy.STATUS_PENDING))
        assertFalse(GradingPollingPolicy.isAwaiting(GradingPollingPolicy.STATUS_READY))
        assertFalse(GradingPollingPolicy.isAwaiting(null))
        assertFalse(GradingPollingPolicy.isAwaiting("weird"))
    }

    // ---- 循环要不要再 GET 一次 ----

    @Test
    fun keepsPollingWhilePendingOrFailedAndStopsAtReady() {
        assertTrue(poll(status = "pending"))
        assertTrue(poll(status = "failed"))
        assertFalse(poll(status = "ready"))
    }

    @Test
    fun unknownStatusAfterASnapshotStopsTheLoop() {
        // `str | None` 的 JSON 列 + 旧会话: 字段缺席/脏值都出现过。拿一个不认识的状态
        // 继续轮 = "永远转圈"的另一种形状; 不可知就等于不再等。
        assertFalse(poll(status = null, sawSnapshot = true))
        assertFalse(poll(status = "", sawSnapshot = true))
        assertFalse(poll(status = "generating", sawSnapshot = true))
    }

    @Test
    fun firstRequestFailureIsTreatedAsJitterNotAsAnAnswer() {
        // 一次快照都没读到 -> 状态还是"不知道", 不能因为 status==null 就收工; 单次丢包
        // 按网络抖动放过 (容忍额度见 MAX_CONSECUTIVE_POLL_FAILURES)。
        assertTrue(poll(status = null, sawSnapshot = false, failures = 1))
        assertFalse(poll(status = null, sawSnapshot = false, failures = 2))
    }

    @Test
    fun consecutiveNetworkFailuresGiveUp() {
        assertTrue(poll(status = "pending", failures = 1))
        assertFalse(poll(status = "pending", failures = 2))
        assertFalse(poll(status = "pending", failures = 3))
    }

    @Test
    fun timeoutWinsOverEverythingElse() {
        // 超时排在"状态还允许轮"之前: 一份永远停在 pending 的快照(作业被重启丢了)
        // 不该把这一页钉死在轮询上。
        assertFalse(
            GradingPollingPolicy.shouldKeepPolling(
                status = "pending",
                sawSnapshot = true,
                consecutiveFailures = 0,
                elapsedMillis = ReviewPollingPolicy.TIMEOUT_MILLIS
            )
        )
        assertTrue(
            GradingPollingPolicy.shouldKeepPolling(
                status = "pending",
                sawSnapshot = true,
                consecutiveFailures = 0,
                elapsedMillis = ReviewPollingPolicy.TIMEOUT_MILLIS - 1
            )
        )
    }

    @Test
    fun cadenceIsBorrowedNotReinvented() {
        // 节奏只取现成的 ReviewPollingPolicy (2s 起探、线性退避、6s 封顶) —— 本文件
        // 一个数字都不另立, 所以这里钉的是"借用的关系"本身。
        assertTrue(
            GradingPollingPolicy.shouldKeepPolling(
                status = "pending",
                sawSnapshot = true,
                consecutiveFailures = 0,
                elapsedMillis = 0L
            )
        )
        assertTrue(ReviewPollingPolicy.nextDelayMillis(0) > 0L)
        assertTrue(
            ReviewPollingPolicy.nextDelayMillis(9) <= ReviewPollingPolicy.MAX_POLL_MILLIS
        )
    }

    private fun poll(
        status: String?,
        sawSnapshot: Boolean = true,
        failures: Int = 0,
        elapsed: Long = 0L
    ): Boolean = GradingPollingPolicy.shouldKeepPolling(
        status = status,
        sawSnapshot = sawSnapshot,
        consecutiveFailures = failures,
        elapsedMillis = elapsed
    )
}
