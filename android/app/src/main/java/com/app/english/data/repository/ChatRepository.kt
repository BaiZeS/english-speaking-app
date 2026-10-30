package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.ThreadCreateRequestDto
import com.app.english.data.remote.ThreadTurnRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.ChatMessage
import com.app.english.domain.model.ChatThread
import com.app.english.domain.model.ThreadSummary
import com.app.english.domain.model.TurnMode
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 一轮提交的结果: 本轮**新增**的那几颗气泡 + 线程的新游标。
 *
 * 后端只回新增部分 (整条线程随 `getThread` 给), 所以 ViewModel 拿到它是**追加**而不是替换 ——
 * 替换会把用户刚发出去那颗气泡在服务端落库前的本地形态冲掉。
 */
data class TurnResult(
    val threadId: String,
    val turnCount: Int,
    val gradingStatus: String,
    val beatIndex: Int,
    val appended: List<ChatMessage>
)

/**
 * v3.0 会话线程的数据面: 会话列表、开线程、取线程、发一轮、删会话。
 *
 * 契约要点 (动手前先读 `docs/compose/spec/dialogue-chat-revamp.md` S2.3-S2.6):
 *
 * - **服务端是唯一事实来源**。旧的 `/dialogue/turn` 让客户端攒 `history[]` 回传, 于是
 *   "回到这个场景接着聊"没有实现基础; 而 v2.3.1 换签名证书要求存量设备卸载重装, 装回来
 *   聊天就断了。
 * - 开线程**幂等**: 同场景二次调用返回同一条线程, 所以"退回列表再点进来"不会叠一层开场白。
 * - [getThread] 同时是**评分回填的通道**: 顶层 `gradingStatus` + 逐颗气泡的 `grade`。
 * - 语音轮**没有**"学员声明语言"这个入参: 后端一律走讯飞 `zh_cn` 中英混读听写, 说了中文
 *   还是英文由服务端从转写文本事后判, 判出来只决定要不要跑英文逐词发音分。
 */
interface ChatRepository {
    suspend fun listThreads(): List<ThreadSummary>
    suspend fun openThread(sceneKey: String): ChatThread
    suspend fun getThread(threadId: String): ChatThread
    suspend fun deleteThread(threadId: String)

    /** 语音传 [audioBase64] (mode=voice), 否则 [text] (mode=text)。 */
    suspend fun submitTurn(
        threadId: String,
        audioBase64: String = "",
        text: String = "",
        recordingRef: String = "",
        modelId: String? = null
    ): TurnResult
}

@Singleton
class ChatRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : ChatRepository {

    private val deviceId: String get() = settingsStore.deviceId

    override suspend fun listThreads(): List<ThreadSummary> =
        api.listThreads(deviceId).map { it.toDomain() }

    override suspend fun openThread(sceneKey: String): ChatThread =
        api.openThread(ThreadCreateRequestDto(sceneKey), deviceId).toDomain()

    override suspend fun getThread(threadId: String): ChatThread =
        api.getThread(threadId, deviceId).toDomain()

    override suspend fun deleteThread(threadId: String) {
        api.deleteThread(threadId, deviceId)
    }

    override suspend fun submitTurn(
        threadId: String,
        audioBase64: String,
        text: String,
        recordingRef: String,
        modelId: String?
    ): TurnResult {
        val mode = if (audioBase64.isNotBlank()) TurnMode.VOICE else TurnMode.TEXT
        val response = api.submitTurn(
            threadId,
            ThreadTurnRequestDto(
                mode = mode,
                audioB64 = audioBase64,
                text = text,
                recordingRef = recordingRef,
                modelId = modelId
            ),
            deviceId
        )
        return TurnResult(
            threadId = response.threadId,
            turnCount = response.turnCount,
            gradingStatus = response.gradingStatus,
            beatIndex = response.beatIndex,
            appended = response.messages.map { it.toDomain() }
        )
    }
}
