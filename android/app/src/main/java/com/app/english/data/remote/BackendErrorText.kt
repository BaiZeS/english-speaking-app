package com.app.english.data.remote

import java.io.IOException
import java.io.InterruptedIOException
import java.net.SocketTimeoutException
import retrofit2.HttpException

/**
 * 会话类错误的**中文文案表**(纯函数, JVM 可测)。
 *
 * 存在的理由是一条真实的观感事故: 后端 `AppError.message` 大部分是英文
 * (`"skip budget exhausted (2/2); finish the remaining steps"`、
 * `"this session already went to review"`、`"session is completed"`), 而
 * OkHttp 读超时的异常 message 就是裸单词 `"timeout"` —— 这些原文此前会被
 * 直接当红字渲染到中文界面上。
 *
 * 取值顺序是刻意的, 且必须是这个顺序:
 * 1. **按 code 命中中文表** —— code 是稳定契约, 文案由客户端掌控, 永不出英文;
 * 2. code 未命中, 而后端 message **本身就含中文** (如 `TRANSCRIPT_UNAVAILABLE`
 *    的「音频无法转写 (讯飞 IAT 未配置或超时), 请改用 text 作答」) —— 后端给了
 *    更具体的诊断, 采纳它;
 * 3. 都不满足 -> 调用方传来的中文兜底。**绝不返回裸英文。**
 *
 * 服务端消息文本本次**保持不动** (改它是对外契约变更, 会打断断言 message 的测试)。
 */
fun sessionErrorCodeText(code: String?, backendMessage: String?, fallback: String): String {
    val mapped = when (code) {
        "SKIP_LIMIT_REACHED" -> "跳过额度已用完 (每场最多 2 步), 请把剩下的步骤做完"
        "MISSION_FINISHED" -> "本场已收工, 去看复盘报告吧"
        "SESSION_CONCURRENT_UPDATE" -> "会话刚在别处被更新, 请退出后重新进入"
        "SESSION_NOT_ACTIVE" -> "本场会话已结束"
        "SESSION_NOT_FOUND" -> "这场练习找不到了, 请退出后重新进入"
        "WRONG_STAGE" -> "当前环节还不能做这一步, 按清单顺序来"
        "STEP_OUT_OF_ORDER" -> "请按清单顺序完成, 先做当前这一步"
        "STEP_ALREADY_DONE" -> "这一步已经做过了"
        "STEP_NOT_FOUND" -> "这一步不属于本课, 请退出后重新进入"
        "MISSION_INPUT_REQUIRED" -> "说点什么或打字再发送"
        "TRANSCRIPT_UNAVAILABLE" -> "这段语音没能转写出文字, 试试打字发送"
        "SESSION_KIND_UNSUPPORTED" -> "这类会话不支持该操作"
        else -> null
    }
    if (mapped != null) return mapped
    if (backendMessage != null && backendMessage.containsCjk()) return backendMessage
    return fallback
}

/**
 * 任意异常的中文文案。收工/提交这类"后果不可见"的动作尤其要老实:
 * 读超时**不代表服务端没做完**, 只代表没在 30s 内把响应送回手机上 ——
 * 所以文案引导用户去结果页/历史里确认, 而不是只说"失败了"让人反复重发。
 */
fun Throwable.sessionMessage(fallback: String): String = when (this) {
    is HttpException -> sessionErrorCodeText(
        code = backendErrorCode(),
        backendMessage = backendErrorMessage(),
        fallback = "$fallback (${code()})"
    )
    // SocketTimeoutException 是 InterruptedIOException 的子类, 顺序不能反。
    is SocketTimeoutException ->
        "服务器响应超过了 30 秒。它可能仍在处理中, 稍等再从「最近复盘」或历史里看结果。"
    is InterruptedIOException ->
        "网络等待超时, 请检查信号后重试一次。"
    is IOException ->
        "连不上服务器, 请检查网络或「设置」里的服务器地址。"
    else -> message?.takeIf { it.containsCjk() } ?: fallback
}

/**
 * 是否含中日韩字形。用来判断后端 message 是否已经本地化过 —— 只看第一个
 * CJK 码点区间, 够用且不必引 ICU; 英文诊断串 (`"session is completed"`) 会正确地
 * 被判为未本地化。
 */
private fun String.containsCjk(): Boolean = any { ch ->
    ch in '\u4E00'..'\u9FFF' ||
        // CJK Unified Ideographs
        ch in '\u3400'..'\u4DBF' ||
        // Ext A
        ch in '\u3040'..'\u30FF' // 平假名/片假名 (万一以后用到)
}
