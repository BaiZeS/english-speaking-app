package com.app.english.data.remote

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import retrofit2.HttpException

/**
 * 会话错误文案表锁 —— 回归的是真实事故: 后端状态机 409 的 message 是英文
 * (`"skip budget exhausted (2/2); finish the remaining steps"`), OkHttp 读超时的
 * 异常 message 是裸单词 `"timeout"`, 而 `BriefingViewModel.userMessage()` 当时
 * **优先取后端 message**, 于是英文原文直达中文界面的红字区。
 */
class BackendErrorTextTest {

    // ---- code mapping -------------------------------------------------------

    @Test
    fun everyKnownStateMachineCodeGetsChineseText() {
        val codes = listOf(
            "SKIP_LIMIT_REACHED",
            "MISSION_FINISHED",
            "SESSION_CONCURRENT_UPDATE",
            "SESSION_NOT_ACTIVE",
            "SESSION_NOT_FOUND",
            "WRONG_STAGE",
            "STEP_OUT_OF_ORDER",
            "STEP_ALREADY_DONE",
            "STEP_NOT_FOUND",
            "MISSION_INPUT_REQUIRED",
            "TRANSCRIPT_UNAVAILABLE",
            "SESSION_KIND_UNSUPPORTED"
        )
        for (code in codes) {
            val text = sessionErrorCodeText(code, backendMessage = null, fallback = "兜底")
            assertTrue(
                "$code must not fall through to the generic fallback: $text",
                text != "兜底"
            )
            assertTrue("$code must render in Chinese: $text", text.containsCjkForTest())
        }
    }

    @Test
    fun skipLimitReachingIsMappedEvenThoughTheBackendSpeaksEnglish() {
        // 这一条就是当初漏网的那个码: 有码、无映射, 英文原文直接上屏。
        val english = "skip budget exhausted (2/2); finish the remaining steps"
        val text = sessionErrorCodeText("SKIP_LIMIT_REACHED", english, fallback = "兜底")
        assertEquals("跳过额度已用完 (每场最多 2 步), 请把剩下的步骤做完", text)
        assertFalse(text.contains("budget"))
    }

    @Test
    fun codeWinsOverBackendMessageSoSurfaceTextIsStable() {
        val mapped = sessionErrorCodeText(
            "WRONG_STAGE",
            "practice is at stage 'mission', not 'briefing'",
            fallback = "兜底"
        )
        assertEquals("当前环节还不能做这一步, 按清单顺序来", mapped)
    }

    @Test
    fun alreadyChineseBackendMessageIsAdoptedWhenTheCodeIsUnknown() {
        // 后端对 IAT 失败给的是带诊断的中文串, 比客户端的泛化文案更有用。
        val detail = "音频无法转写 (讯飞 IAT 未配置或超时), 请改用 text 作答"
        assertEquals(detail, sessionErrorCodeText("SOME_FUTURE_CODE", detail, fallback = "兜底"))
    }

    @Test
    fun englishMessageIsNeverSurfacedVerbatimAsFallback() {
        val text = sessionErrorCodeText(null, "session is completed", fallback = "操作失败")
        assertEquals("操作失败", text)
    }

    // ---- Throwable mapping --------------------------------------------------

    @Test
    fun httpExceptionIsDecodedFromItsErrorEnvelope() {
        val boom = httpException(
            409,
            """{"error":{"code":"SKIP_LIMIT_REACHED",""" +
                """"message":"skip budget exhausted (2/2); finish the remaining steps"}}"""
        )
        val text = boom.sessionMessage(fallback = "提交失败")
        assertEquals("跳过额度已用完 (每场最多 2 步), 请把剩下的步骤做完", text)
    }

    @Test
    fun httpExceptionWithoutAnEnvelopeFallsBackToTheStatusLineNotRawEnglish() {
        val boom = httpException(500, "<html>gateway blew up</html>")
        val text = boom.sessionMessage(fallback = "提交失败")
        assertEquals("提交失败 (500)", text)
    }

    @Test
    fun readTimeoutIsReportedAsStillProcessingNotAsTheWordTimeout() {
        // 用户报告的第五个症状里, 屏幕上那个"超时提示"其实就是这个裸英文单词。
        val text = SocketTimeoutException("timeout").sessionMessage(fallback = "发送失败")
        assertFalse("must not leak the bare English token", text.trim() == "timeout")
        assertTrue(
            "must tell the learner the server may still be working",
            text.contains("仍在处理")
        )
        assertTrue(text.containsCjkForTest())
    }

    @Test
    fun interruptedIoGetsItsOwnNetworkText() {
        val text = object : java.io.InterruptedIOException("read timed out") {}.sessionMessage("兜底")
        assertTrue(text.contains("网络等待超时"))
    }

    @Test
    fun connectionFailurePointsAtNetworkAndServerAddress() {
        val text = ConnectException("Failed to connect").sessionMessage(fallback = "发送失败")
        assertTrue(text.contains("服务器"))
    }

    @Test
    fun nonChineseExceptionMessageIsReplacedByTheCallerFallback() {
        val text = IllegalStateException("Something went very wrong").sessionMessage("操作失败")
        assertEquals("操作失败", text)
    }

    @Test
    fun chineseExceptionMessageFromOurOwnCodeIsKept() {
        // 录音/编码路径抛的异常本来就写中文, 不该被泛化文案盖掉。
        val text = IllegalStateException("录音启动失败").sessionMessage("操作失败")
        assertEquals("录音启动失败", text)
    }

    @Test
    fun ioExceptionIsCaughtAfterSocketTimeoutBySpecificity() {
        // 顺序断言: SocketTimeoutException 是 InterruptedIOException 的子类,
        // 若两分支写反, 慢服务器会被误报成普通网络超时。
        assertTrue(SocketTimeoutException("x") is java.io.InterruptedIOException)
        val text = IOException("broken pipe").sessionMessage("兜底")
        assertTrue(text.contains("连不上服务器"))
    }

    // ---- helpers ------------------------------------------------------------

    private fun httpException(status: Int, body: String): HttpException {
        // okhttp3.Response is the wire type; retrofit2.Response.error() is what
        // wraps it into something HttpException can carry (and what makes
        // errorBody() readable). Casting one to the other is a ClassCastException.
        val raw = okhttp3.Response.Builder()
            .request(Request.Builder().url("http://backend.test/api/v1/sessions/x").build())
            .protocol(Protocol.HTTP_1_1)
            .code(status)
            .message("status $status")
            .build()
        val errorBody = body.toResponseBody("application/json".toMediaType())
        return HttpException(retrofit2.Response.error<Any>(errorBody, raw))
    }

    private fun String.containsCjkForTest(): Boolean = any { it in '\u4E00'..'\u9FFF' }
}
