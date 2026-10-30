package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

@Serializable
data class TtsResponseDto(
    @SerialName("audio_url") val audioUrl: String,
    @SerialName("duration_ms") val durationMs: Int,
    // "mimo"=真实合成, "stub"=占位假音频 (未配 MIMO_API_KEY). 旧后端无此字段时取默认值.
    val source: String = "stub"
)

@Serializable
data class LlmModelDto(
    val id: String,
    @SerialName("display_name") val displayName: String,
    val provider: String,
    val description: String = ""
)

@Serializable
data class LlmModelsResponseDto(
    val models: List<LlmModelDto>,
    @SerialName("default_model") val defaultModel: String
)

@Serializable
data class AppVersionResponseDto(
    @SerialName("latest_version") val latestVersion: String,
    @SerialName("min_supported_version") val minSupportedVersion: String,
    @SerialName("apk_url") val apkUrl: String,
    @SerialName("release_notes") val releaseNotes: String = "",
    @SerialName("force_update") val forceUpdate: Boolean = false
)

@Serializable
data class DialogueSceneDto(
    val id: String,
    val title: String,
    val description: String,
    @SerialName("title_en") val titleEn: String = "",
    @SerialName("description_en") val descriptionEn: String = "",
    val kind: String = "catalog",
    /** v3.0 群聊: 这一场的 AI 角色 (2-3 个)。会话列表摆头像组、聊天页把气泡上的
     * `role_id` 翻译成人, 都读这里。旧 APK `ignoreUnknownKeys`, 多出来的键不炸解析。 */
    val roles: List<SceneRoleDto> = emptyList(),
    @SerialName("user_role") val userRole: String = ""
)

/** 群聊里的一个 AI 角色; `voice` 是后端 TTS 音色, 客户端只透传给 `/tts` 兜底请求。 */
@Serializable
data class SceneRoleDto(
    @SerialName("role_id") val roleId: String = "",
    val name: String = "",
    @SerialName("name_en") val nameEn: String = "",
    val voice: String = ""
)

@Serializable
data class DialogueScenesResponseDto(
    val scenes: List<DialogueSceneDto>,
    @SerialName("default_scene") val defaultScene: String
)

/**
 * `POST /dialogue/scenes/custom` 的入参 (§3 C2/C3): 学员自己写的一段场景描述。
 * 长度门 4..200 在客户端与后端各有一份 (后端是契约, 客户端只是别让他白等一次 422)。
 */
@Serializable
data class CustomSceneRequestDto(
    @SerialName("scene_brief") val sceneBrief: String,
    @SerialName("device_id") val deviceId: String? = null,
    @SerialName("user_id") val userId: String? = null
)
