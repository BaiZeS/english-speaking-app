package com.app.english.ui.chat

import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioRecorder
import com.app.english.audio.RecordingStore
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * 一次录音的采集、编码与本机留档。
 *
 * 从 ViewModel 里分出来的原因是职责而不是行数: VM 管的是"屏幕上现在有什么", 这里管的
 * 是"麦克风、PCM 与磁盘"。两件事混在一起时, 录音失败与提交失败会共用同一个错误通道,
 * 用户看到的就是一句分不清是"没录到"还是"没送出去"的提示。
 */
class ChatRecorder @Inject constructor(
    private val recorder: AudioRecorder,
    private val encoder: AudioEncoder,
    private val recordingStore: RecordingStore
) {
    val level: StateFlow<Float> get() = recorder.levelFlow

    private val _recording = MutableStateFlow(false)
    val recording: StateFlow<Boolean> = _recording.asStateFlow()

    /** 本机录音 `文件名 -> file:// URI`; 服务端只回显文件名, 路径只有本机知道。 */
    private val takenByName = mutableMapOf<String, String>()

    /** 只读视图: 让"按文件名找回本机录音"这条逻辑能被纯函数单测覆盖。 */
    val taken: Map<String, String> get() = takenByName

    suspend fun start() {
        _recording.value = true
        recorder.start()
    }

    fun cancel() {
        _recording.value = false
        recorder.cancel()
    }

    /** 一次录音的产物: 要送后端的 base64 + 可回放的本机 URI。 */
    data class Take(val base64: String, val fileName: String, val localUri: String)

    /**
     * 结束录音并编码。返回 null = 这一枪没录到东西 (太短 / 被系统打断)。
     *
     * 落盘失败**不算**失败: 送后端要紧, 回听是次要功能, 少了本机文件只是这条气泡点不开。
     */
    suspend fun finish(): Take? {
        _recording.value = false
        val pcm: File = recorder.stop() ?: return null
        val encoded = encoder.encode(pcm)
        val playable = runCatching { recordingStore.saveChatTake(pcm) }.getOrNull()
        val uri = playable?.let { file ->
            "file://${file.absolutePath}".also { takenByName[file.name] = it }
        }.orEmpty()
        return Take(base64 = encoded, fileName = playable?.name.orEmpty(), localUri = uri)
    }
}
