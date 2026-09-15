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
 * 判级结果是 `/complete` 的一次性响应, 首屏数据经单例 holder 搬运(异步判级下
 * 也可经 `GET /assessment/{id}/result` 读回, 但 holder 仍是零延迟的首选路径)。
 * holder 为空(如进程死在搬运间隙)时结果页直接给「没有找到本次判级结果」错误态,
 * 并提示稍后去「我的-能力画像」查看 —— 不在这里做 GET /ability 兜底。
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

    /**
     * 实时声量脉冲条的电平源(计划 §2.6 E4 点名的缺口: 这一页以前既没有电平管线、也
     * **从来没画过**录音条)。直接转发录音器的 [AudioRecorder.levelFlow] —— 平滑 VU
     * 包络就是脉冲条的驱动, UI 层不再造第二套平滑; 也不复制进 [_flow](25 Hz 整屏
     * 重组, 由叶子组合项自己 collect)。电平清零时机由录音器独家决定; 提交那几秒的
     * "定格"观感是 UI 端 RecordingPulseMeter 捕获峰值的职责。
     */
    val micLevel: StateFlow<Float> get() = audioRecorder.levelFlow

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
        if (_isRecording.value) return
        _isRecording.value = true
        viewModelScope.launch {
            try {
                audioRecorder.start(
                    maxDurationMs = AudioRecorder.MAX_TAKE_MS,
                    onAutoStop = ::stopRecordingAndSubmit
                )
            } catch (e: Exception) {
                _isRecording.value = false
                _flow.update { it.copy(error = "录音启动失败：${e.message}") }
            }
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

    /** 收卷判级: 202 在途就轮询 GET result 到终态; 幂等, 失败可重试。 */
    fun complete() {
        if (attemptId.isEmpty()) return
        viewModelScope.launch {
            _flow.update { reduceAssessment(it, AssessmentEvent.CompleteStarted) }
            try {
                val judgement = pollJudgeResult(
                    assessmentRepository,
                    attemptId,
                    assessmentRepository.complete(attemptId)
                )
                if (judgement == null) {
                    // 轮询超时: 判级作业仍在服务端跑(画像最终会亮), 诚实告知而不是报错。
                    _flow.update {
                        reduceAssessment(it, AssessmentEvent.Failed(JUDGE_STILL_RUNNING_CN))
                    }
                    return@launch
                }
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

    /** ON_STOP safety net: finish the live take (send, don't lose it). */
    fun stopRecordingIfActive() {
        if (_isRecording.value) stopRecordingAndSubmit()
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        // Gate the cancel: the recorder is a singleton now, so clearing this screen
        // must not tear down some other screen's live take.
        if (_isRecording.value) audioRecorder.cancel()
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
    /** 判级写入后的权威画像(含 CEFR 徽章值); 拉不到不影响主结果, stub 时兜底四维。 */
    val profile: AbilityProfile? = null,
    /** 「重新判级」在途: 防重入, 按钮置 busy。 */
    val isPolling: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class AssessmentResultViewModel @Inject constructor(
    private val resultHolder: AssessmentResultHolder,
    private val abilityRepository: AbilityRepository,
    private val assessmentRepository: AssessmentRepository
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
            refreshProfile()
        }
    }

    /**
     * 「重新判级」(stub 结果的翻案入口): 重跑 complete + 轮询, 到终态就刷新结果。
     * 服务端只对 source=stub 的存量允许重判; 防重入靠 [AssessmentResultUiState.isPolling]。
     */
    fun rejudge() {
        val current = _state.value.judgement ?: return
        if (_state.value.isPolling) return
        viewModelScope.launch {
            _state.update { it.copy(isPolling = true, error = null) }
            try {
                val judgement = pollJudgeResult(
                    assessmentRepository,
                    current.attemptId,
                    assessmentRepository.complete(current.attemptId)
                )
                if (judgement == null) {
                    _state.update { it.copy(isPolling = false, error = JUDGE_STILL_RUNNING_CN) }
                    return@launch
                }
                _state.update { it.copy(isPolling = false, judgement = judgement) }
                refreshProfile()
            } catch (e: Exception) {
                Timber.w(e, "assessment rejudge failed")
                _state.update {
                    it.copy(isPolling = false, error = e.message ?: "重新判级失败, 请稍后再试")
                }
            }
        }
    }

    private suspend fun refreshProfile() {
        // 判级已写画像 -> 顺手刷新权威徽章; 失败不阻塞结果展示。
        try {
            val profile = abilityRepository.getProfile(DEFAULT_ABILITY_DAYS)
            _state.update { it.copy(profile = profile) }
        } catch (e: Exception) {
            Timber.w(e, "ability refresh after assessment failed")
        }
    }
}
