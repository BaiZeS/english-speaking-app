package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.backendErrorMessage
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
import retrofit2.HttpException

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
            try {
                val loaded = sessionRepository.get(sessionId)
                snapshot = loaded
                _course.value = loaded.course
                _state.value = loaded.briefing.toUiState()
            } catch (e: Exception) {
                _state.update { it.copy(error = e.userMessage()) }
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
        try {
            audioRecorder.start()
            _isRecording.value = true
            _state.update { it.copy(error = null) }
        } catch (e: Exception) {
            _state.update { it.copy(error = "录音启动失败：${e.message}") }
        }
    }

    fun stopRecordingAndSubmit() {
        if (!_isRecording.value) return
        val step = _state.value.currentStep?.id ?: return
        _isRecording.value = false
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

/** 后端 message(TRANSCRIPT_UNAVAILABLE 等码本身是中文)优先, 退回异常文本。 */
internal fun Throwable.userMessage(): String = when (this) {
    is HttpException -> backendErrorMessage() ?: "提交失败 (${code()})"
    else -> message ?: "提交失败"
}
