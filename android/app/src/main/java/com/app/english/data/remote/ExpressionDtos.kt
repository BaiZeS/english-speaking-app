package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/** `GET /expressions` 列表项(`ExpressionDto`)。 */
@Serializable
data class ExpressionDto(
    val id: String,
    val polished: String = "",
    val original: String = "",
    @SerialName("explanation_cn") val explanationCn: String = "",
    @SerialName("source_label") val sourceLabel: String = "manual",
    @SerialName("scene_id") val sceneId: String = "",
    @SerialName("session_id") val sessionId: String = "",
    @SerialName("created_at") val createdAt: String = ""
)

/** `POST /expressions` 收藏请求(后端按 normalized 润色句去重)。 */
@Serializable
data class CreateExpressionRequestDto(
    @SerialName("device_id") val deviceId: String? = null,
    val polished: String,
    val original: String = "",
    @SerialName("explanation_cn") val explanationCn: String = "",
    @SerialName("source_label") val sourceLabel: String = "manual",
    @SerialName("scene_id") val sceneId: String = "",
    @SerialName("session_id") val sessionId: String = ""
)

/** `created=false` = 归一化去重命中, 返回的是既有那条。 */
@Serializable
data class CreateExpressionResponseDto(val expression: ExpressionDto, val created: Boolean = true)
