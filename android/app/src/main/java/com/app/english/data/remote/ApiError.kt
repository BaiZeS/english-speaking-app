package com.app.english.data.remote

import kotlinx.serialization.Serializable
import retrofit2.HttpException

/**
 * 后端 `AppError` 的统一错误体: `{"error": {"code": "...", "message": "..."}}`。
 * 状态机类 409 要靠 **code** 分支(SKIP_LIMIT_REACHED / MISSION_FINISHED /
 * SESSION_CONCURRENT_UPDATE …), message 只作展示。
 */
@Serializable
data class ApiErrorEnvelopeDto(val error: ApiErrorBodyDto = ApiErrorBodyDto())

@Serializable
data class ApiErrorBodyDto(val code: String = "", val message: String = "")

/** 从 HTTP 错误响应里摘机器可读的 error.code; 解不出来给 null(调用方走兜底文案)。 */
fun HttpException.backendErrorCode(): String? = parseEnvelope()?.error?.code?.takeIf {
    it.isNotEmpty()
}

/** 后端给的面向用户的 message(TRANSCRIPT_UNAVAILABLE 等码本身就是中文文案)。 */
fun HttpException.backendErrorMessage(): String? =
    parseEnvelope()?.error?.message?.takeIf { it.isNotEmpty() }

private fun HttpException.parseEnvelope(): ApiErrorEnvelopeDto? = try {
    val body = response()?.errorBody()?.string() ?: return null
    val json = kotlinx.serialization.json.Json { ignoreUnknownKeys = true }
    json.decodeFromString<ApiErrorEnvelopeDto>(body)
} catch (_: Exception) {
    null
}
