package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.TranslateRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.AppVersion
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.LlmModel
import com.app.english.domain.model.TtsAudio
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 目录、语音条兜底合成、模型目录与 OTA 版本 —— v3.0 之后这条仓储只剩支撑面,
 * 对话本身的数据面在 [ChatRepository]。
 */
interface EnglishRepository {
    suspend fun listDialogueScenes(): List<DialogueScene>

    /**
     * 语音条的按需补合成。后端在请求内已经试过一回 (预算 3s), 给不出 URL 时气泡带
     * `audioPending=true` —— 这条兜底路**必须存在**, 否则一次 TTS 抖动就等于没声音。
     */
    suspend fun getTtsAudio(text: String, voice: String): TtsAudio

    suspend fun listLlmModels(): List<LlmModel>
    suspend fun getAppVersion(): AppVersion

    /** 长按翻译: 只服务没有现成双语的那条消息 (有对照的气泡在客户端本地切换)。 */
    suspend fun translate(text: String, targetLang: String): String
}

@Singleton
class EnglishRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : EnglishRepository {
    override suspend fun listDialogueScenes(): List<DialogueScene> =
        api.listDialogueScenes(settingsStore.deviceId).scenes.map { it.toDomain() }

    override suspend fun getTtsAudio(text: String, voice: String): TtsAudio =
        api.getTts(text, voice).toDomain()

    override suspend fun listLlmModels(): List<LlmModel> =
        api.listLlmModels().models.map { it.toDomain() }

    override suspend fun getAppVersion(): AppVersion = api.getAppVersion().toDomain()

    override suspend fun translate(text: String, targetLang: String): String =
        api.translate(TranslateRequestDto(text, targetLang)).translated
}
