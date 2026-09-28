package com.app.english.update

import java.io.IOException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * v2.2.4/VC13: 「检查更新失败」不再困死用户的行为锁。
 *
 * 生产实锤: 后端端口被别的项目占掉, 更新检查必失败, 而当时的 UX 是三件事叠在一起 ——
 * ① `Failed(e.message)` 把原始异常文本(kotlinx.serialization 会把整段响应体嵌进
 * message)直接渲染进弹窗; ② `onDismissFailure = { check(force = true) }` 让「知道了」
 * 变成「立刻再失败一次」, 弹窗关掉就原样回来; ③ `onResume` 又打一次非静默的 check,
 * 于是切个后台回来再中一次。结果是模态框锁死整个 App, 连「设置」(改服务器地址的
 * 唯一入口)都进不去。本版三处分别由
 * [sanitizeUpdateFailureMessage] / [dismissedFailureState] / [collapseSilentFailure]
 * 这三个纯函数钉住 —— 与 [decideUpdate] 同一套「从 Android 类里剥出来, JVM 可测」。
 */
class AppUpdateFailureHandlingTest {

    // ---- 折叠: Failed -> Idle, 不重查 ------------------------------------------------

    @Test
    fun dismissFailure_collapsesFailedToIdle() {
        val dismissed = dismissedFailureState(UpdateCheckState.Failed(UPDATE_CHECK_FAILURE_MESSAGE))
        assertEquals(UpdateCheckState.Idle, dismissed)
    }

    @Test
    fun dismissFailure_leavesEveryOtherStateAlone() {
        // 弹窗只在 Failed 时存在; 别的状态被 dismiss 改动会把升级提示误吞掉。
        val remote = UpdateCheckState.UpdateAvailable(
            UpdateInfo("1.4.0", "2.0.0", "0.0.0", "https://example.invalid/a.apk", "", false)
        )
        assertEquals(remote, dismissedFailureState(remote))
        assertEquals(UpdateCheckState.Checking, dismissedFailureState(UpdateCheckState.Checking))
        assertEquals(
            UpdateCheckState.UpToDate("2.0.0"),
            dismissedFailureState(UpdateCheckState.UpToDate("2.0.0"))
        )
    }

    // ---- 静默检查: 失败不外露 --------------------------------------------------------

    @Test
    fun silentCheckFailure_staysIdleInsteadOfFailed() {
        val state = collapseSilentFailure(UPDATE_CHECK_FAILURE_MESSAGE, silent = true)
        assertEquals(UpdateCheckState.Idle, state)
        assertTrue("静默失败不许渲染弹窗", state !is UpdateCheckState.Failed)
    }

    @Test
    fun nonSilentCheckFailure_stillSurfacesFailed() {
        // 「至少弹一次」这条不许被静默化顺手废掉 —— 冷启动与手动检查仍然要能告知。
        assertEquals(
            UpdateCheckState.Failed(UPDATE_CHECK_FAILURE_MESSAGE),
            collapseSilentFailure(UPDATE_CHECK_FAILURE_MESSAGE, silent = false)
        )
    }

    // ---- 文案: 原始异常绝不进 UI ----------------------------------------------------

    @Test
    fun serializationErrorMessageIsNeverShownVerbatim() {
        // 本次事故的真实形状: kotlinx.serialization 的 message 内嵌整段响应体。
        val raw = "Expected string literal, but had <html><head><title>502 Bad Gateway</title>" +
            "</head><body>nginx</body></html> instead (at Line: 1, Col: 1)."
        val message = sanitizeUpdateFailureMessage(IllegalStateException(raw))
        val state = UpdateCheckState.Failed(message)
        assertEquals(UPDATE_CHECK_FAILURE_MESSAGE, state.message)
    }

    @Test
    fun connectionFailureGetsTheFriendlyNetworkText() {
        val text = sanitizeUpdateFailureMessage(
            IOException("Failed to connect to /118.89.58.84:5173")
        )
        assertEquals("无法连接更新服务，请检查网络后重试", text)
    }

    @Test
    fun nullMessageDoesNotLeakIntoTheDialog() {
        assertEquals(
            UPDATE_CHECK_FAILURE_MESSAGE,
            sanitizeUpdateFailureMessage(IllegalStateException())
        )
    }

    @Test
    fun cleanChineseAppLevelMessageIsKept() {
        // 自家代码抛的中文消息本来就是给人看的, 盖成通用文案反而丢信息。
        val text = sanitizeUpdateFailureMessage(IOException("服务器地址未配置，请先到设置里填写"))
        assertEquals("服务器地址未配置，请先到设置里填写", text)
    }

    @Test
    fun chineseMessageCarryingHtmlOrJsonIsStillRejected() {
        // 中文 + 响应体残片 = 后端错误页, 不能因为"含中文"就放行上屏。
        val text = sanitizeUpdateFailureMessage(
            IOException("服务不可用 <html><body>error</body></html>")
        )
        assertEquals(UPDATE_CHECK_FAILURE_MESSAGE, text)
    }

    @Test
    fun overLongMessageIsRejectedEvenWhenChinese() {
        val text = sanitizeUpdateFailureMessage(IOException("详" + "细".repeat(200)))
        assertEquals(UPDATE_CHECK_FAILURE_MESSAGE, text)
    }

    // ---- 端到端: manager 折叠出的那一格 ---------------------------------------------

    @Test
    fun failureStateComposedEndToEnd_isFailedWithSanitizedMessage() {
        val boom = IllegalStateException("Json {\"latest_version\": ...} is not valid")
        val state = collapseSilentFailure(sanitizeUpdateFailureMessage(boom), silent = false)
        assertTrue(state is UpdateCheckState.Failed)
        assertEquals(UPDATE_CHECK_FAILURE_MESSAGE, (state as UpdateCheckState.Failed).message)
    }
}
