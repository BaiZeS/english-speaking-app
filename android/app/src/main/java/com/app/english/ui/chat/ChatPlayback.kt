package com.app.english.ui.chat

import com.app.english.audio.AudioPlayer
import com.app.english.domain.model.ChatMessage
import com.app.english.domain.model.TtsAudio
import javax.inject.Inject
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

/**
 * 气泡的播放: 谁在响、响完没有、放不出来时怎么办。
 *
 * 从 ViewModel 里分出来的理由是职责而不是行数: VM 管"屏幕上现在有什么", 这里管
 * ExoPlayer 与"这句是谁说的用什么音色"。混在一起时, 换场景要记得停播、释放要记得
 * 取消合成 —— 这类"忘了清"的 bug 一旦发生在 VM 里, 表现是回列表再进来还在放上一场
 * 的声音, 很难归因。
 */
class ChatPlayback @Inject constructor(private val player: AudioPlayer) {
    private val _playingId = MutableStateFlow<String?>(null)
    val playingId: StateFlow<String?> = _playingId.asStateFlow()

    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()

    /** 角色 → TTS 音色。开场景时填一次, 之后只读。 */
    private var voiceOf: Map<String, String> = emptyMap()

    fun setVoices(voices: Map<String, String>) {
        voiceOf = voices
    }

    fun voiceFor(roleId: String): String = voiceOf[roleId].orEmpty()

    /**
     * 播一颗气泡。失败时把**中文原因 + Media3 错误码**交回界面。
     *
     * 错误必须外露: v2.3.1 之前 `onPlayerError` 只写日志再走"播完"语义, release 包连
     * Timber 都没 plant, 用户面对静音只能猜。错误码就是下一轮定位的取证通道。
     */
    fun play(
        message: ChatMessage,
        localUri: String?,
        scope: CoroutineScope,
        onFallbackAudio: suspend () -> TtsAudio?
    ) {
        _error.value = null
        if (needsTtsFallback(message)) {
            scope.launch {
                val audio = onFallbackAudio() ?: return@launch
                play(
                    message.copy(audioUrl = audio.audioUrl, audioPending = false),
                    localUri,
                    scope
                ) {
                    null
                }
            }
            return
        }
        val url = message.audioUrl ?: localUri
        if (url.isNullOrBlank()) return
        _playingId.value = message.id
        player.play(
            url,
            onError = { reason ->
                _playingId.value = null
                _error.value = reason
            },
            onCompletion = { _playingId.value = null }
        )
    }

    fun stop() {
        player.stop()
        _playingId.value = null
    }

    fun release() {
        player.release()
    }
}
