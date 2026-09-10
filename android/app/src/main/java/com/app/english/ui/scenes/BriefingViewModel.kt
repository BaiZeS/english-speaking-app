package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.sessionMessage
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.FoundationStepSpec
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.domain.model.SessionSnapshot
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * 打基础页(计划 §6.4 BriefingScreen): 服务端状态机驱动 —— 进页 GET 恢复快照,
 * 提交只发 text/audio, 进度一律以响应的 briefing 为准(reducer 纯函数见
 * [reduceBriefing])。
 */
@HiltViewModel
class BriefingViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioRecorder: AudioRecorder,
    private val audioEncoder: AudioEncoder,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sessionId: String =
        savedStateHandle.get<String>(Route.SceneBriefing.ARG_SESSION_ID).orEmpty()

    private val _state = MutableStateFlow(BriefingUiState())
    val state: StateFlow<BriefingUiState> = _state.asStateFlow()

    private val _course = MutableStateFlow<SceneCourseDetail?>(null)
    val course: StateFlow<SceneCourseDetail?> = _course.asStateFlow()

    private val _isRecording = MutableStateFlow(false)
    val isRecording: StateFlow<Boolean> = _isRecording.asStateFlow()

    /**
     * 滚动波形窗口, 直接转发录音器持有的那一份(不复制进 reduceBriefing 的状态机:
     * 那是 25 Hz 的整屏重组, 而且状态机不该知道麦克风)。喂的是**未平滑**的逐帧峰值
     * —— VU 那条 `levelFlow` 的包络会把音节糊成一坨。收工不在这里清: 评分期间学员
     * 还在看刚说完的那一条, 清空时机由 `AudioRecorder` 独家决定。
     */
    val waveform: StateFlow<List<Float>> get() = audioRecorder.waveformFlow

    private val _isPlayingRef = MutableStateFlow(false)
    val isPlayingRef: StateFlow<Boolean> = _isPlayingRef.asStateFlow()

    private var snapshot: SessionSnapshot? = null

    /** 文本草稿(翻译主路径 / 复述·造句备选)——输入框私有, 不进状态机。 */
    var draft: String = ""
        private set

    init {
        restore()
    }

    /** 崩溃恢复: 按 GET /sessions/{id} 的服务端状态机渲染, 不自算进度。 */
    fun restore() {
        viewModelScope.launch {
            _state.update { reduceBriefing(it, BriefingEvent.Restoring) }
            try {
                val loaded = sessionRepository.get(sessionId)
                snapshot = loaded
                _course.value = loaded.course
                _state.value = loaded.briefing.toUiState()
            } catch (e: Exception) {
                // Failed 顺带清 isLoading: "加载失败"与"仍在恢复"是两回事, 界面据此
                // 给「重试」, 而不是一句永远亮着的"正在恢复会话…" + 底部误报额度。
                _state.update {
                    reduceBriefing(
                        it,
                        BriefingEvent.Failed(e.sessionMessage("加载打基础清单失败"))
                    )
                }
            }
        }
    }

    /** 当前步的题目内容(题型卡片的数据源)。 */
    fun currentSpec(): FoundationStepSpec? {
        val step = _state.value.currentStep ?: return null
        return _course.value?.briefing?.firstOrNull { it.id == step.id }
    }

    fun updateDraft(text: String) {
        draft = text
    }

    /** 文本作答(翻译主路径 / 复述·造句备选)。 */
    fun submitText() {
        val step = _state.value.currentStep?.id ?: return
        val text = draft.trim()
        if (text.isEmpty() || _state.value.isSubmitting) return
        viewModelScope.launch { submit(step, text = text, audioB64 = null) }
    }

    fun startRecording() {
        if (_isRecording.value || _state.value.isSubmitting) return
        // 乐观翻位同 Mission: DOWN 当帧进入录音态, 硬件构造在 IO 协程里完成。
        _isRecording.value = true
        viewModelScope.launch {
            try {
                audioRecorder.start(
                    maxDurationMs = AudioRecorder.MAX_TAKE_MS,
                    onAutoStop = ::stopRecordingAndSubmit
                )
            } catch (e: Exception) {
                _isRecording.value = false
                _state.update { it.copy(error = "录音启动失败：${e.message}") }
            }
        }
    }

    fun stopRecordingAndSubmit() {
        if (!_isRecording.value) return
        val step = _state.value.currentStep?.id ?: return
        _isRecording.value = false
        // 波形不清: 评分期间这条形状还要留在屏上(见 waveform 的 KDoc)。
        viewModelScope.launch {
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                submit(step, text = null, audioB64 = base64)
            } finally {
                file.delete()
            }
        }
    }

    /** 生命周期兜底: ON_STOP 时走停+提交(宁发不丢)。 */
    fun stopRecordingIfActive() {
        if (_isRecording.value) stopRecordingAndSubmit()
    }

    fun skipCurrent() {
        val step = _state.value.currentStep?.id ?: return
        if (!_state.value.canSkip) return
        viewModelScope.launch {
            _state.update { it.copy(isSubmitting = true, error = null) }
            try {
                val outcome = sessionRepository.skipStep(sessionId, step)
                _state.update { current ->
                    reduceBriefing(current, BriefingEvent.Graded(outcome.grade, outcome.briefing))
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = e.userMessage()) }
            }
        }
    }

    /** 原句示范发音(read_along/retell), /tts 的 stub URL 照常播。 */
    fun playReference(text: String) {
        if (_isPlayingRef.value || text.isBlank()) return
        viewModelScope.launch {
            _isPlayingRef.value = true
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) { _isPlayingRef.value = false }
            } catch (_: Exception) {
                _isPlayingRef.value = false
            }
        }
    }

    private suspend fun submit(stepId: String, text: String?, audioB64: String?) {
        _state.update { it.copy(isSubmitting = true, error = null) }
        try {
            val outcome = sessionRepository.submitStep(sessionId, stepId, text, audioB64)
            _state.update { current ->
                reduceBriefing(current, BriefingEvent.Graded(outcome.grade, outcome.briefing))
            }
        } catch (e: Exception) {
            _state.update { it.copy(isSubmitting = false, error = e.userMessage()) }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_isRecording.value) audioRecorder.cancel()
    }
}

/**
 * 提交类异常的中文文案。
 *
 * 曾经优先取后端 `message`, 而状态机 409 的 message 是英文
 * (`"skip budget exhausted (2/2); finish the remaining steps"`), 读超时的异常
 * message 更是裸单词 `"timeout"` —— 两者都直上过中文界面的红字区。现统一走
 * [sessionMessage]: code 命中中文表 > 后端中文 message > 调用方兜底, 永不出英文。
 */
internal fun Throwable.userMessage(): String = sessionMessage(fallback = "提交失败")
