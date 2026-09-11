package com.app.english.ui.scenes

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 「收工」重复提交守卫的锁(计划 §2.6 E2)。
 *
 * 生产日志是硬证据: 学员那场练习 00:31:01 点收工, 服务端 00:32:09 才把总评写完(降级),
 * 手机的 socket 早在 ~00:31:31 就死了; 之后 00:34:42/44/52/56 **四次** `finish-mission`
 * 全吃 409 —— 因为他每次重点都真发出去了一个请求。这一组用例锁的就是"点两下只发一次"。
 */
class MissionFinishGuardTest {

    @Test
    fun aSecondTapWhileTheFirstIsInFlightFiresNothing() {
        // 这就是那 4 连 409 的成因: 第一发还在天上, finished 仍是 false, 于是守卫放行。
        assertEquals(
            FinishTap.SUBMIT,
            MissionFinishGuard.tapOf(finished = false, inFlight = false)
        )
        assertEquals(
            FinishTap.IGNORE_IN_FLIGHT,
            MissionFinishGuard.tapOf(finished = false, inFlight = true)
        )
    }

    /**
     * 在途**排在** `finished` 之前。反过来的话, 一个已经收工的会话在"另一发还在天上"时
     * 会被判成"再发一次收工", 而 409 之后照样要跳复盘页 —— 白跑一趟还多一条红字。
     */
    @Test
    fun inFlightOutranksFinished() {
        assertEquals(
            FinishTap.IGNORE_IN_FLIGHT,
            MissionFinishGuard.tapOf(finished = true, inFlight = true)
        )
    }

    @Test
    fun alreadyFinishedNavigatesWithoutAnotherRequest() {
        // 二次收工(含崩溃恢复后重进)的正确行为: 不请求, 直接进复盘页。
        assertEquals(
            FinishTap.OPEN_REVIEW,
            MissionFinishGuard.tapOf(finished = true, inFlight = false)
        )
    }

    /**
     * 409 `MISSION_FINISHED` 是**幂等成功**而不是失败: 它意味着服务端早已关掉这一场
     * (通常就是上一次请求其实成了, 只是响应没能回到这台手机上)。
     */
    @Test
    fun theAlreadyFinishedConflictIsNotAnError() {
        assertTrue(MissionFinishGuard.failureMeansAlreadyFinished("MISSION_FINISHED"))
        assertFalse(MissionFinishGuard.failureMeansAlreadyFinished("WRONG_STAGE"))
        // 没有 code(读超时、断网、非 JSON 错误体)时绝不按"已收工"处理。
        assertFalse(MissionFinishGuard.failureMeansAlreadyFinished(null))
        assertFalse(MissionFinishGuard.failureMeansAlreadyFinished(""))
    }

    /**
     * 收工在途时「← 退出」不能再开弹窗 —— 那是重复提交的第二条路(弹窗关了, 按钮还在)。
     * 而**发一轮**在途时仍要能打开: 一轮可以挂到 23s, 那时把退出按钮打死会让人连
     * "算了, 收工"都按不到, 用一个更糟的体验去换一个更安全的体验。
     */
    @Test
    fun exitDialogReopensOnlyWhenNoFinishIsInFlight() {
        assertFalse(MissionFinishGuard.canOpenExitDialog(isFinishing = true))
        assertTrue(MissionFinishGuard.canOpenExitDialog(isFinishing = false))
    }

    /**
     * `inFlight` 必须同时盖住"发一轮/要提示"和"收工": 只用 `isSubmitting` 会漏掉后者,
     * 而收工自己**不**置 `isSubmitting`(它是一条独立的路, 不该让输入框以为自己又发了一轮)。
     */
    @Test
    fun inFlightCoversBothTheTurnAndTheFinishRequest() {
        assertFalse(MissionUiState().inFlight)
        assertTrue(MissionUiState(isSubmitting = true).inFlight)
        assertTrue(MissionUiState(isFinishing = true).inFlight)
    }

    /**
     * `finished` 与 `isFinishing` 是两件事, 且不可互相代替: 服务端可能早已收工而客户端
     * 从没成功过一次(超时路径), 也可能反过来还在发请求。把两者捏成一个布尔就是原 bug。
     */
    @Test
    fun finishedAndIsFinishingStayIndependentFlags() {
        // 服务端已关闭本场, 而客户端这边请求还在飞 / 早已掉线: 两位必须能分开。
        assertTrue(MissionUiState(finished = true, isFinishing = false).finished)
        assertFalse(MissionUiState(finished = true, isFinishing = false).isFinishing)
        assertFalse(MissionUiState(finished = false, isFinishing = true).finished)
        assertTrue(MissionUiState(finished = false, isFinishing = true).isFinishing)
    }

    /**
     * 失败态用的是 `finishError`(那句中文)而不是一个布尔 + 通用 `error`: 失败出口与
     * "要说什么"是同一件事, 拆成两位就会有一位忘了清 —— 而 `error` 那一列同时承担着
     * 发轮次的错误, 混用会让人在气泡流末尾找出口。
     */
    @Test
    fun theFinishFailureKeepsItsOwnMessageSlot() {
        assertNull(MissionUiState().finishError)
        assertEquals("连不上服务器", MissionUiState(finishError = "连不上服务器").finishError)
        // 收工失败不把话塞进气泡流那条 error 上。
        assertNull(MissionUiState(finishError = "x").error)
    }
}
