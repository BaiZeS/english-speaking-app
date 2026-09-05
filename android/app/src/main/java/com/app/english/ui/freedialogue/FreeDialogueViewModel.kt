package com.app.english.ui.freedialogue

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.audio.RecordingStore
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.DialogueMessageDto
import com.app.english.data.repository.BooksRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.HistoryRepository
import com.app.english.data.repository.MistakeWordRepository
import com.app.english.domain.model.DialogueLine
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.DialogueSession
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.navigation.Route
import com.app.english.ui.score.LineScoreResult
import com.app.english.ui.score.ScoreSession
import com.app.english.ui.score.ScoreSessionHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * 聊天气泡模型。
 *
 * [text] 存**协议值** (用户回合 = 识别原文, 识别不到则为空串), 与发给
 * /dialogue/turn 的 history 逐字一致 —— 中文占位提示只发生在渲染层
 * ([FreeDialogueScreen] 按 [hasTranscript] 兜底显示), 不再回流给模型 (P8·2d)。
 */
data class FreeDialogueMessage(
    val role: String,
    val text: String,
    val isUser: Boolean,
    /** false = 用户回合没有识别到任何 transcript (text 为空)。 */
    val hasTranscript: Boolean = true
)

data class FreeDialogueScore(val suggestedReply: String, val result: ScoreResult)

data class FreeDialogueUiState(
    val isLoading: Boolean = true,
    val isLoadingScenes: Boolean = false,
    val scenes: List<DialogueScene> = emptyList(),
    val selectedSceneId: String = "",
    val sceneId: String = "",
    val title: String = "自由对话",
    val messages: List<FreeDialogueMessage> = emptyList(),
    val suggestedReply: String = "",
    val isPlayingReference: Boolean = false,
    val isRecording: Boolean = false,
    val isSubmitting: Boolean = false,
    val currentScore: ScoreResult? = null,
    val scores: List<FreeDialogueScore> = emptyList(),
    val error: String? = null,
    val finished: Boolean = false
)

@HiltViewModel
class FreeDialogueViewModel @Inject constructor(
    private val repository: EnglishRepository,
    private val booksRepository: BooksRepository,
    private val historyRepository: HistoryRepository,
    private val mistakeWordRepository: MistakeWordRepository,
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val recordingStore: RecordingStore,
    private val settingsStore: SettingsStore,
    private val scoreSessionHolder: ScoreSessionHolder,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    private val lessonId: Int = requireNotNull(
        savedStateHandle.get<Int>(Route.FreeDialogue.ARG_LESSON_ID)
    ) { "lessonId argument required" }
    private val book: String =
        savedStateHandle.get<String>(Route.FreeDialogue.ARG_BOOK) ?: "nce1"

    private val _state = MutableStateFlow(FreeDialogueUiState())
    val state: StateFlow<FreeDialogueUiState> = _state.asStateFlow()

    init {
        loadScenes()
    }

    fun selectScene(sceneId: String) {
        if (sceneId == _state.value.selectedSceneId) return
        settingsStore.setSelectedSceneId(sceneId)
        generate(sceneId)
    }

    private fun loadScenes() {
        viewModelScope.launch {
            _state.update { it.copy(isLoadingScenes = true) }
            val scenes = try {
                booksRepository.listDialogueScenes()
            } catch (e: Exception) {
                Timber.w(e, "Failed to load dialogue scenes")
                emptyList()
            }
            val storedSceneId = settingsStore.getSelectedSceneId()
            val initial = storedSceneId?.takeIf { id -> scenes.any { it.id == id } }
                ?: scenes.firstOrNull()?.id
                ?: FALLBACK_SCENE
            if (initial != storedSceneId) {
                settingsStore.setSelectedSceneId(initial)
            }
            _state.update {
                it.copy(
                    scenes = scenes,
                    selectedSceneId = initial ?: "",
                    isLoadingScenes = false
                )
            }
            generate(initial ?: FALLBACK_SCENE)
        }
    }

    fun generate() {
        val scene = _state.value.selectedSceneId.ifBlank { FALLBACK_SCENE }
        generate(scene)
    }

    private fun generate(sceneId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            _state.value = try {
                val session = repository.generateDialogue(
                    sceneId,
                    "adult",
                    settingsStore.getSelectedModelId()
                )
                session.toUiState()
            } catch (e: Exception) {
                _state.value.copy(isLoading = false, error = e.message ?: "加载自由对话失败")
            }
        }
    }

    private fun DialogueSession.toUiState(): FreeDialogueUiState = FreeDialogueUiState(
        isLoading = false,
        sceneId = sceneId,
        title = title,
        messages = lines.map { it.toUiMessage() },
        suggestedReply = suggestedReply
    )

    private fun DialogueLine.toUiMessage(): FreeDialogueMessage = FreeDialogueMessage(
        role = role,
        text = text,
        isUser = isUser
    )

    fun playLatestAssistant() {
        val message = _state.value.messages.lastOrNull { !it.isUser } ?: return
        if (_state.value.isPlayingReference || _state.value.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingReference = true, error = null) }
            try {
                val tts = repository.getTtsAudio(message.text, settingsStore.getVoice())
                if (tts.isStub) {
                    _state.update {
                        it.copy(
                            isPlayingReference = false,
                            error = "AI 语音未配置（后端缺 MIMO_API_KEY），当前无真实语音"
                        )
                    }
                    return@launch
                }
                audioPlayer.play(tts.audioUrl) {
                    _state.update { current -> current.copy(isPlayingReference = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "AI 语音播放失败：${e.message}")
                }
            }
        }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.isSubmitting) return
        viewModelScope.launch {
            try {
                audioRecorder.start()
                _state.update { it.copy(isRecording = true, currentScore = null, error = null) }
            } catch (e: Exception) {
                _state.update { it.copy(error = "录音启动失败：${e.message}") }
            }
        }
    }

    fun stopAndSubmit() {
        val current = _state.value
        // P8·2c: 只有「正在录音」才是提交前提。参考回答为空不再拦截 ——
        // 评分 ref 走 scoringRefText() 的兜底 (最后一条 assistant 台词)。
        if (!current.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isRecording = false, isSubmitting = true) }
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
                return@launch
            }
            val lineId = "free-${current.scores.size + 1}"
            val saved = retainRecording(lineId, file)
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                if (saved != null) file.delete()
                val refText = scoringRefText(current)
                val result = repository.score(
                    lessonId = lessonId,
                    lineId = lineId,
                    refText = refText,
                    audioBase64 = base64,
                    mode = "free_dialogue"
                )
                collectMistakeWords(lineId, result)
                val history =
                    turnHistory(current.messages) + DialogueMessageDto(role = "user", text = "")
                val next = repository.dialogueTurn(
                    current.sceneId,
                    history,
                    base64,
                    settingsStore.getSelectedModelId()
                )
                val recognized = next.recognizedText.orEmpty()
                _state.update {
                    it.copy(
                        isSubmitting = false,
                        currentScore = result,
                        scores = it.scores + FreeDialogueScore(refText, result),
                        messages = it.messages + FreeDialogueMessage(
                            role = "user",
                            text = recognized,
                            isUser = true,
                            hasTranscript = recognized.isNotBlank()
                        ) + FreeDialogueMessage(
                            role = "assistant",
                            text = next.replyText,
                            isUser = false
                        ),
                        suggestedReply = next.suggestedReply
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = "对话评分失败：${e.message}") }
            }
        }
    }

    /**
     * Persists the raw take as a WAV via [RecordingStore] for later replay.
     * Retention failure never blocks scoring; returns null in that case.
     */
    private suspend fun retainRecording(lineId: String, file: File): File? = try {
        withContext(Dispatchers.IO) {
            recordingStore.saveRecording(book, lessonId, lineId, file)
        }
    } catch (e: Exception) {
        Timber.w(e, "Failed to retain recording")
        null
    }

    /** Feeds weak words from a successful score into the mistake-word ledger. */
    private suspend fun collectMistakeWords(lineId: String, result: ScoreResult) {
        try {
            mistakeWordRepository.collectFromResult(book, lessonId, lineId, result)
        } catch (e: Exception) {
            Timber.w(e, "Failed to collect mistake words")
        }
    }

    fun finish() {
        val current = _state.value
        if (current.scores.isEmpty()) {
            _state.update { it.copy(error = "至少完成一轮回答后再结束练习") }
            return
        }
        val results = current.scores.map { it.result }
        val session = ScoreSession(
            lessonTitle = current.title,
            roleName = "AI 自由对话",
            totalScore = results.map { it.total }.average(),
            pronunciation = results.map { it.pronunciation }.average(),
            fluency = results.map { it.fluency }.average(),
            completeness = results.map { it.completeness }.average(),
            suggestion = results.mapNotNull { it.suggestion }.lastOrNull(),
            source = if (results.any { it.isStub }) "stub" else "xunfei",
            lineCount = current.scores.size,
            lineResults = current.scores.mapIndexed { index, scored ->
                LineScoreResult(
                    lineId = "free-${index + 1}",
                    text = scored.suggestedReply,
                    total = scored.result.total,
                    wordScores = scored.result.wordDetails
                )
            }
        )
        scoreSessionHolder.session = session
        viewModelScope.launch {
            try {
                historyRepository.write(
                    book = book,
                    lessonId = lessonId,
                    lineId = "free-session",
                    audioPath = "free_session_${System.currentTimeMillis()}",
                    scoreTotal = session.totalScore,
                    scorePronunciation = session.pronunciation,
                    scoreFluency = session.fluency,
                    scoreCompleteness = session.completeness
                )
            } catch (e: Exception) {
                Timber.e(e, "Failed to write free dialogue history")
            }
            _state.update { it.copy(finished = true) }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }

    private companion object {
        // Used when /dialogue/scenes returns an empty list (offline / older backend).
        const val FALLBACK_SCENE = "daily_conversation"
    }
}

/**
 * P8·2c: 本轮评分的参考句。suggestedReply 有值就用它; 为空 (模型没给建议 /
 * 生成回包缺字段) 时兜底最后一条 assistant 台词 —— 用户照样可以录音提交,
 * 不再被空建议卡死。两者皆空时返回空串, 由 /score 422 诚实报错。
 */
internal fun scoringRefText(state: FreeDialogueUiState): String =
    state.suggestedReply.ifBlank { state.messages.lastOrNull { !it.isUser }?.text.orEmpty() }

/**
 * P8·2d: /dialogue/turn 的历史构造。用户回合只会带**识别原文或空串**
 * (text 即协议值, 见 [FreeDialogueMessage] 注释), UI 的中文占位提示永不
 * 回流进模型上下文 —— 服务端 P3 起按结构 (末尾 user 回合) 判断, 老包的
 * 「（本轮自由回答）」占位由后端兼容层处理, 新客户端不再生产任何中文哨兵。
 */
internal fun turnHistory(messages: List<FreeDialogueMessage>): List<DialogueMessageDto> =
    messages.map {
        DialogueMessageDto(role = if (it.isUser) "user" else "assistant", text = it.text)
    }
