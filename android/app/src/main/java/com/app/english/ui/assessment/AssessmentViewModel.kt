package com.app.english.ui.assessment

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.backendErrorCode
import com.app.english.data.remote.backendErrorMessage
import com.app.english.data.repository.AbilityRepository
import com.app.english.data.repository.AssessmentRepository
import com.app.english.data.repository.DEFAULT_ABILITY_DAYS
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.AbilityProfile
import com.app.english.domain.model.AssessmentBank
import com.app.english.domain.model.AssessmentJudgement
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import timber.log.Timber

/**
 * 结果页与做题页之间的一次性交接(T7 的 SelectedHistoryHolder 同款做法):
 * 判级结果是 `/complete` 的一次性响应, 没有按 attempt 读回的 GET 端点, 用单例
 * holder 搬运; holder 为空时结果页自读 `GET /ability` 兜底(判级已写入画像)。
 */
@Singleton
class AssessmentResultHolder @Inject constructor() {
    private var judgement: AssessmentJudgement? = null

    fun put(result: AssessmentJudgement) {
        judgement = result
    }

    fun consume(): AssessmentJudgement? = judgement
}

// ====== 引导页 ======

data class AssessmentIntroUiState(
    val isLoading: Boolean = true,
    val questionCount: Int = 0,
    val estimatedMinutes: Int = 0,
    val error: String? = null
)

@HiltViewModel
class AssessmentIntroViewModel @Inject constructor(
    private val assessmentRepository: AssessmentRepository
) : ViewModel() {
    private val _state = MutableStateFlow(AssessmentIntroUiState())
    val state: StateFlow<AssessmentIntroUiState> = _state.asStateFlow()

    init {
        loadBank()
    }

    /** 引导页只读题库摘要(GET /assessment 零身份), 用时/题数按题库算, 不写死。 */
    fun loadBank() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val bank: AssessmentBank = assessmentRepository.bank()
                _state.update {
                    it.copy(
                        isLoading = false,
                        questionCount = bank.total,
                        estimatedMinutes = estimatedAssessmentMinutes(bank.questions)
                    )
                }
            } catch (e: Exception) {
                Timber.w(e, "assessment bank load failed")
                _state.update { it.copy(isLoading = false, error = e.message ?: "题库加载失败") }
            }
        }
    }
}

// ====== 做题页 ======

@HiltViewModel
class AssessmentViewModel @Inject constructor(
    private val assessmentRepository: AssessmentRepository,
    private val resultHolder: AssessmentResultHolder,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioRecorder: AudioRecorder,
    private val audioEncoder: AudioEncoder,
    private val audioPlayer: AudioPlayer
) : ViewModel() {
    private val _flow = MutableStateFlow(AssessmentFlowState())
    val flow: StateFlow<AssessmentFlowState> = _flow.asStateFlow()

    private val _isRecording = MutableStateFlow(false)
    val isRecording: StateFlow<Boolean> = _isRecording.asStateFlow()

    private var attemptId: String = ""
    private var textDraft: String = ""

    init {
        start()
    }

    fun start() {
        viewModelScope.launch {
            _flow.value = AssessmentFlowState()
            try {
                val session = assessmentRepository.start()
                attemptId = session.attemptId
                _flow.value = reduceAssessment(
                    _flow.value,
                    AssessmentEvent.Started(session.questions)
                )
            } catch (e: Exception) {
                _flow.update {
                    it.copy(error = e.assessmentMessage())
                }
            }
        }
    }

    fun updateDraft(text: String) {
        textDraft = text
    }

    fun submitText() {
        val text = textDraft.trim()
        val question = _flow.value.current ?: return
        if (text.isEmpty() || !_flow.value.canSubmitText) return
        // 草稿**不**在这里清: 提交失败时用户可以原样重交; 成功后翻题由界面层清空。
        viewModelScope.launch {
            dispatchAnswer(question.no, text = text, audioB64 = null)
        }
    }

    fun startRecording() {
        if (_flow.value.phase != AssessmentPhase.ANSWERING || _flow.value.audioBlocked) return
        try {
            audioRecorder.start()
            _isRecording.value = true
        } catch (e: Exception) {
            _flow.update { it.copy(error = "录音启动失败：${e.message}") }
        }
    }

    fun stopRecordingAndSubmit() {
        if (!_isRecording.value) return
        _isRecording.value = false
        val question = _flow.value.current ?: return
        viewModelScope.launch {
            val file = try {
                audioRecorder.stop()
            } catch (e: Exception) {
                _flow.update { it.copy(error = "录音失败，请重试") }
                return@launch
            }
            if (file == null) {
                _flow.update { it.copy(error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                dispatchAnswer(question.no, text = null, audioB64 = base64)
            } finally {
                file.delete()
            }
        }
    }

    private suspend fun dispatchAnswer(questionNo: Int, text: String?, audioB64: String?) {
        _flow.update { reduceAssessment(it, AssessmentEvent.SubmitStarted) }
        try {
            val outcome = assessmentRepository.answer(attemptId, questionNo, text, audioB64)
            _flow.update {
                reduceAssessment(it, AssessmentEvent.AnswerAccepted(outcome.answersCount))
            }
            if (_flow.value.phase == AssessmentPhase.JUDGING) complete()
        } catch (e: Exception) {
            val code = (e as? HttpException)?.backendErrorCode()
            if (code == "TRANSCRIPT_UNAVAILABLE") {
                _flow.update {
                    reduceAssessment(it, AssessmentEvent.TranscriptUnavailable)
                }
            } else {
                _flow.update {
                    reduceAssessment(it, AssessmentEvent.Failed(e.assessmentMessage()))
                }
            }
        }
    }

    /** 收卷判级(分钟级 LLM 调用, 界面挂 spinner); 幂等, 失败可重试。 */
    fun complete() {
        if (attemptId.isEmpty()) return
        viewModelScope.launch {
            _flow.update { reduceAssessment(it, AssessmentEvent.CompleteStarted) }
            try {
                val judgement = assessmentRepository.complete(attemptId)
                resultHolder.put(judgement)
                _flow.update { reduceAssessment(it, AssessmentEvent.Judged) }
            } catch (e: Exception) {
                _flow.update {
                    reduceAssessment(it, AssessmentEvent.Failed(e.assessmentMessage()))
                }
            }
        }
    }

    /** 样句 TTS(跟读题点小喇叭听标准读音); stub 音频同样有 URL, 照常播。 */
    fun playSample(text: String) {
        viewModelScope.launch {
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) { }
            } catch (e: Exception) {
                Timber.w(e, "assessment tts failed")
            }
        }
    }

    fun consumeError() = _flow.update { reduceAssessment(it, AssessmentEvent.ErrorShown) }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        audioRecorder.cancel()
        _isRecording.value = false
    }
}

private fun Exception.assessmentMessage(): String = when (this) {
    is HttpException -> assessmentErrorCodeText(backendErrorCode(), backendErrorMessage())
    else -> message ?: "提交失败, 请重试"
}

// ====== 结果页 ======

data class AssessmentResultUiState(
    val isLoading: Boolean = true,
    /** holder 里的一次性判级结果(直接来自 /complete 响应)。 */
    val judgement: AssessmentJudgement? = null,
    /** 判级写入后的权威画像(含 CEFR 徽章值); 拉不到也不影响主结果展示。 */
    val profile: AbilityProfile? = null,
    val error: String? = null
)

@HiltViewModel
class AssessmentResultViewModel @Inject constructor(
    private val resultHolder: AssessmentResultHolder,
    private val abilityRepository: AbilityRepository
) : ViewModel() {
    private val _state = MutableStateFlow(AssessmentResultUiState())
    val state: StateFlow<AssessmentResultUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            val judgement = resultHolder.consume()
            _state.update { it.copy(isLoading = false, judgement = judgement) }
            // 判级已写画像 -> 顺手刷新权威徽章; 失败不阻塞结果展示。
            try {
                val profile = abilityRepository.getProfile(DEFAULT_ABILITY_DAYS)
                _state.update { it.copy(profile = profile) }
            } catch (e: Exception) {
                Timber.w(e, "ability refresh after assessment failed")
            }
        }
    }
}
