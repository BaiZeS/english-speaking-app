package com.app.english.ui.freedialogue

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.DialogueMessageDto
import com.app.english.data.repository.BooksRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.HistoryRepository
import com.app.english.domain.model.DialogueLine
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.DialogueSession
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.navigation.Route
import com.app.english.ui.score.LineScoreResult
import com.app.english.ui.score.ScoreSession
import com.app.english.ui.score.ScoreSessionHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

data class FreeDialogueMessage(val role: String, val text: String, val isUser: Boolean)

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
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val settingsStore: SettingsStore,
    private val scoreSessionHolder: ScoreSessionHolder,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    private val lessonId: Int = requireNotNull(
        savedStateHandle.get<Int>(Route.FreeDialogue.ARG_LESSON_ID)
    ) { "lessonId argument required" }

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
                Timber.w(e, 'Failed to load dialogue scenes')
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
                val url = repository.getTtsAudioUrl(message.text, settingsStore.getVoice())
                audioPlayer.play(url) {
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
        if (!current.isRecording || current.suggestedReply.isBlank()) return
        viewModelScope.launch {
            _state.update { it.copy(isRecording = false, isSubmitting = true) }
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                val lineId = "free-${current.scores.size + 1}"
                val result = repository.score(
                    lessonId = lessonId,
                    lineId = lineId,
                    refText = current.suggestedReply,
                    audioBase64 = base64,
                    mode = "free_dialogue"
                )
                val history = current.messages.map {
                    DialogueMessageDto(
                        role = if (it.isUser) "user" else "assistant",
                        text = it.text
                    )
                } + DialogueMessageDto(role = "user", text = "（本轮自由回答）")
                val next = repository.dialogueTurn(
                    current.sceneId,
                    history,
                    base64,
                    settingsStore.getSelectedModelId()
                )
                _state.update {
                    it.copy(
                        isSubmitting = false,
                        currentScore = result,
                        scores = it.scores + FreeDialogueScore(current.suggestedReply, result),
                        messages = it.messages + FreeDialogueMessage(
                            role = "user",
                            text = next.recognizedText ?: "（本轮自由回答）",
                            isUser = true
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
            } finally {
                file.delete()
            }
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
