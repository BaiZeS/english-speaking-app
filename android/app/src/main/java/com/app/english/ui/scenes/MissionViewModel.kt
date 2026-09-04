package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.backendErrorCode
import com.app.english.data.remote.backendErrorMessage
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.ExpressionRepository
import com.app.english.data.repository.PolishCollectRequest
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.HintData
import com.app.english.domain.model.MissionTurnResult
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.SessionSnapshot
import com.app.english.domain.model.TaskChip
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
import timber.log.Timber

/** 聊天列表里的一条气泡(turnIndex 给 LazyColumn 的 key 用)。 */
sealed interface MissionBubble {
    val turnIndex: Int

    /** AI 台词(点击播 TTS)。 */
    data class Ai(val text: String, override val turnIndex: Int) : MissionBubble

    /** 用户台词; 无转写时诚实显示占位(不再编造字面量)。 */
    data class User(
        val text: String,
        val hasTranscript: Boolean,
        val polish: PolishBubble?,
        override val turnIndex: Int
    ) : MissionBubble
}

/** 409/400 等状态机错误的 Snackbar 文案(按后端 error.code 分支)。 */
fun missionErrorCodeText(code: String?, fallback: String?): String = when (code) {
    "MISSION_FINISHED" -> "本场已收工, 去看复盘报告吧"
    "SESSION_CONCURRENT_UPDATE" -> "会话刚在别处被更新, 请退出后重新进入"
    "SESSION_NOT_ACTIVE" -> "本场会话已结束"
    "WRONG_STAGE" -> "请先完成打基础步骤"
    "MISSION_INPUT_REQUIRED" -> "说点什么或打字再发送"
    "TRANSCRIPT_UNAVAILABLE" -> "这段语音没能转写出文字, 试试打字发送"
    else -> fallback ?: "发送失败, 请重试"
}

data class MissionUiState(
    val isLoading: Boolean = true,
    val bubbles: List<MissionBubble> = emptyList(),
    val checklist: List<TaskChip> = emptyList(),
    val turnCount: Int = 0,
    val maxTurns: Int = 0,
    val personaCn: String = "",
    val suggestion: String = "",
    val isSubmitting: Boolean = false,
    val isRecording: Boolean = false,
    val isPlaying: Boolean = false,
    val hint: HintData? = null,
    val hintWarnsScore: Boolean = false,
    val finished: Boolean = false,
    /** 一闪而过的提示(新任务达成 reason / 收藏结果)。 */
    val snackbar: String? = null,
    val error: String? = null
) {
    /** HUD「第 n/max 轮 · 已勾 m/k 项」。 */
    val hudText: String
        get() = "第 $turnCount/$maxTurns 轮 · 已勾 ${taskProgressLabel(checklist)} 项"
}

/**
 * 实战对话页(计划 §6.4 MissionScreen, 聊天软件式): 状态机驱动, 服务端持权威
 * 进度; 润色嵌在用户气泡下, 任务 chips 横滑, 退出需确认并 finish-mission。
 */
@HiltViewModel
class MissionViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val expressionRepository: ExpressionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioRecorder: AudioRecorder,
    private val audioEncoder: AudioEncoder,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sessionId: String =
        savedStateHandle.get<String>(Route.SceneMission.ARG_SESSION_ID).orEmpty()

    private val _state = MutableStateFlow(MissionUiState())
    val state: StateFlow<MissionUiState> = _state.asStateFlow()

    private var snapshot: SessionSnapshot? = null
    private var sceneId: String = ""

    init {
        restore()
    }

    /** 恢复: 打基础没打完就退回; 否则按快照重绘气泡与清单。 */
    fun restore() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val loaded = sessionRepository.get(sessionId)
                snapshot = loaded
                sceneId = loaded.sceneId
                val mission = loaded.mission
                if (loaded.stage == "briefing" || mission == null) {
                    _state.update {
                        it.copy(isLoading = false, error = BRIEFING_NOT_DONE, finished = true)
                    }
                    return@launch
                }
                val course = loaded.course
                val opening = mission.openingA.ifBlank { course?.mission?.openingA.orEmpty() }
                val bubbles = buildList {
                    add(MissionBubble.Ai(text = opening, turnIndex = 0))
                    mission.turns.forEach { turn ->
                        add(
                            MissionBubble.User(
                                text = turn.transcript,
                                hasTranscript = turn.transcript.isNotBlank(),
                                polish = turn.polish.toBubbleOrNull(),
                                turnIndex = turn.turnIndex
                            )
                        )
                        add(MissionBubble.Ai(text = turn.reply, turnIndex = turn.turnIndex))
                    }
                }
                _state.update {
                    it.copy(
                        isLoading = false,
                        bubbles = bubbles,
                        checklist = mission.tasks,
                        turnCount = mission.turnCount,
                        maxTurns = mission.maxTurns,
                        personaCn = course?.mission?.personaCn.orEmpty(),
                        finished = loaded.status != "active"
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.userMessage()) }
            }
        }
    }

    fun updateDraft(text: String) {
        draft = text
    }

    private var draft: String = ""

    fun sendText() {
        val text = draft.trim()
        if (text.isEmpty() || _state.value.isSubmitting || _state.value.finished) return
        draft = ""
        viewModelScope.launch { sendTurn(text = text, audioB64 = null) }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.isSubmitting) return
        try {
            audioRecorder.start()
            _state.update { it.copy(isRecording = true, error = null) }
        } catch (e: Exception) {
            _state.update { it.copy(error = "录音启动失败：${e.message}") }
        }
    }

    fun stopRecordingAndSend() {
        if (!_state.value.isRecording) return
        _state.update { it.copy(isRecording = false) }
        viewModelScope.launch {
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                sendTurn(text = null, audioB64 = base64)
            } finally {
                file.delete()
            }
        }
    }

    private suspend fun sendTurn(text: String?, audioB64: String?) {
        _state.update { it.copy(isSubmitting = true, error = null) }
        try {
            val result = sessionRepository.missionTurn(sessionId, text, audioB64)
            consumeTurnResult(result)
        } catch (e: Exception) {
            _state.update { it.copy(isSubmitting = false, error = e.missionMessage()) }
        }
    }

    private fun consumeTurnResult(result: MissionTurnResult) {
        val turn = result.turn
        _state.update { current ->
            current.copy(
                isSubmitting = false,
                bubbles = current.bubbles + MissionBubble.User(
                    text = turn.transcript,
                    hasTranscript = turn.transcript.isNotBlank(),
                    polish = turn.polish.toBubbleOrNull(),
                    turnIndex = turn.turnIndex
                ) + MissionBubble.Ai(text = turn.reply, turnIndex = turn.turnIndex),
                checklist = result.checklist,
                turnCount = result.turnCount,
                maxTurns = result.maxTurns,
                suggestion = turn.suggestion,
                finished = result.finished,
                hint = null,
                hintWarnsScore = false,
                snackbar = result.turn.newlyDone.firstOrNull()?.evidence
            )
        }
        if (result.review != null) {
            // auto-finish(到 max_turns): 复盘已随响应返回, 直接进复盘页。
            _state.update { it.copy(finished = true, snackbar = "回合用完, 已自动收工") }
        }
    }

    fun requestHint() {
        if (_state.value.isSubmitting || _state.value.finished) return
        viewModelScope.launch {
            _state.update { it.copy(isSubmitting = true, error = null) }
            try {
                val hint = sessionRepository.hint(sessionId)
                _state.update {
                    it.copy(isSubmitting = false, hint = hint, hintWarnsScore = true)
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = e.missionMessage()) }
            }
        }
    }

    fun dismissHint() = _state.update { it.copy(hint = null) }

    /** AI 气泡点击播放: 沿用 /tts; stub 音频同样有 URL, 照常播。 */
    fun playAiBubble(text: String) {
        if (_state.value.isPlaying) return
        viewModelScope.launch {
            _state.update { it.copy(isPlaying = true) }
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) { _state.update { s -> s.copy(isPlaying = false) } }
            } catch (e: Exception) {
                Timber.w(e, "mission tts failed")
                _state.update { it.copy(isPlaying = false, snackbar = "语音播放失败") }
            }
        }
    }

    /** 润色气泡 ⭐收藏 -> POST /expressions(重复收藏后端返回既有条目)。 */
    fun collectPolish(polish: PolishSuggestion) {
        viewModelScope.launch {
            try {
                val (created, _) = expressionRepository.collect(
                    PolishCollectRequest(
                        polished = polish.polished,
                        original = polish.original,
                        explanationCn = polish.explanationCn,
                        sourceLabel = "mission",
                        sceneId = sceneId,
                        sessionId = sessionId
                    )
                )
                _state.update {
                    it.copy(snackbar = if (created) "已收进表达库" else "这句话已经在表达库里")
                }
            } catch (e: Exception) {
                _state.update { it.copy(snackbar = "收藏失败: ${e.message}") }
            }
        }
    }

    fun consumeSnackbar() = _state.update { it.copy(snackbar = null) }

    fun dismissError() = _state.update { it.copy(error = null) }

    /** 退出确认后的收工: finish-mission -> 复盘页; 已 finished 的直接走。 */
    fun finishAndReview(onOpenReview: (String) -> Unit) {
        if (_state.value.finished) {
            onOpenReview(sessionId)
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(isSubmitting = true) }
            try {
                sessionRepository.finishMission(sessionId)
                _state.update { it.copy(isSubmitting = false, finished = true) }
                onOpenReview(sessionId)
            } catch (e: Exception) {
                // 已经收工的幂等场景(409 MISSION_FINISHED)照样进复盘。
                val code = (e as? HttpException)?.backendErrorCode()
                _state.update { it.copy(isSubmitting = false) }
                if (code == "MISSION_FINISHED") {
                    onOpenReview(sessionId)
                } else {
                    _state.update { it.copy(error = e.missionMessage()) }
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }
}

private fun Throwable.missionMessage(): String = when (this) {
    is HttpException -> missionErrorCodeText(backendErrorCode(), backendErrorMessage())
    else -> message ?: "发送失败, 请重试"
}

private const val BRIEFING_NOT_DONE = "实战还没解锁, 先把打基础清单走完"
