package com.app.english.ui.player

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.HistoryRepository
import com.app.english.domain.model.Line
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

private const val MIN_SCORE_TO_ADVANCE = 60.0

data class ScoredLine(val line: Line, val result: ScoreResult)

data class PlayerUiState(
    val isLoading: Boolean = true,
    val lessonTitle: String = "",
    val roleName: String = "",
    val lines: List<Line> = emptyList(),
    val currentIndex: Int = 0,
    val isPlayingReference: Boolean = false,
    val isRecording: Boolean = false,
    val isSubmitting: Boolean = false,
    val currentScore: ScoreResult? = null,
    val lineScores: List<ScoredLine> = emptyList(),
    val hasRetaken: Boolean = false,
    val error: String? = null,
    val finished: Boolean = false
) {
    val currentLine: Line? get() = lines.getOrNull(currentIndex)
    val isLastLine: Boolean get() = currentIndex >= lines.lastIndex

    // Spec §4.1: a line scoring < 60 must be re-recorded once before advancing.
    val canAdvance: Boolean
        get() = currentScore != null && (currentScore.total >= MIN_SCORE_TO_ADVANCE || hasRetaken)
}

@HiltViewModel
class PlayerViewModel @Inject constructor(
    private val repository: EnglishRepository,
    private val historyRepository: HistoryRepository,
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val settingsStore: SettingsStore,
    private val scoreSessionHolder: ScoreSessionHolder,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val lessonId: Int = requireNotNull(savedStateHandle.get<Int>(Route.Player.ARG_LESSON_ID)) {
        "lessonId argument required"
    }
    private val roleName: String =
        requireNotNull(savedStateHandle.get<String>(Route.Player.ARG_ROLE_NAME)) {
            "roleName argument required"
        }

    private val _state = MutableStateFlow(PlayerUiState())
    val state: StateFlow<PlayerUiState> = _state.asStateFlow()

    init {
        loadLesson()
    }

    fun reload() = loadLesson()

    private fun loadLesson() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            _state.value = try {
                val lesson = repository.getLessonRoles(lessonId, BOOK)
                val role = lesson.roles.firstOrNull { r -> r.name == roleName }
                if (role == null) {
                    _state.value.copy(isLoading = false, error = "角色不存在: $roleName")
                } else {
                    PlayerUiState(
                        isLoading = false,
                        lessonTitle = lesson.title,
                        roleName = role.name,
                        lines = role.lines,
                        currentIndex = 0
                    )
                }
            } catch (e: Exception) {
                _state.value.copy(isLoading = false, error = e.message ?: "加载课文失败")
            }
        }
    }

    fun playReference() {
        val line = _state.value.currentLine ?: return
        if (_state.value.isPlayingReference || _state.value.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingReference = true, error = null) }
            try {
                val url = repository.getTtsAudioUrl(line.text, settingsStore.getVoice())
                audioPlayer.play(url) {
                    _state.update { state -> state.copy(isPlayingReference = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "TTS 播放失败: ${e.message}")
                }
            }
        }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.isSubmitting) return
        viewModelScope.launch {
            try {
                audioRecorder.start()
                _state.update {
                    it.copy(
                        isRecording = true,
                        currentScore = null,
                        error = null,
                        hasRetaken = it.hasRetaken || it.currentScore != null
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(error = "录音启动失败: ${e.message}") }
            }
        }
    }

    fun stopAndSubmit() {
        if (!_state.value.isRecording) return
        val line = _state.value.currentLine ?: return
        viewModelScope.launch {
            _state.update { it.copy(isRecording = false, isSubmitting = true) }
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                val result = repository.score(lessonId, line.id, line.text, base64)
                _state.update {
                    it.copy(
                        isSubmitting = false,
                        currentScore = result,
                        lineScores = it.lineScores + ScoredLine(line, result)
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = "评分失败: ${e.message}") }
            } finally {
                file.delete()
            }
        }
    }

    fun nextLine() {
        val state = _state.value
        if (state.isRecording || state.isSubmitting) return
        if (state.isLastLine) {
            finish(state)
        } else {
            audioPlayer.stop()
            _state.update {
                it.copy(
                    currentIndex = it.currentIndex + 1,
                    currentScore = null,
                    hasRetaken = false,
                    error = null
                )
            }
        }
    }

    private fun finish(state: PlayerUiState) {
        val scores = state.lineScores
        if (scores.isEmpty()) {
            _state.update { it.copy(finished = true) }
            return
        }
        val session = ScoreSession(
            lessonTitle = state.lessonTitle,
            roleName = state.roleName,
            totalScore = scores.map { it.result.total }.average(),
            pronunciation = scores.map { it.result.pronunciation }.average(),
            fluency = scores.map { it.result.fluency }.average(),
            completeness = scores.map { it.result.completeness }.average(),
            suggestion = scores.mapNotNull { it.result.suggestion }.lastOrNull(),
            lineCount = scores.size,
            lineResults = scores.map { scored ->
                LineScoreResult(
                    lineId = scored.line.id,
                    text = scored.line.text,
                    total = scored.result.total,
                    wordScores = scored.result.wordDetails
                )
            }
        )
        scoreSessionHolder.session = session
        viewModelScope.launch {
            try {
                val lastLine = state.currentLine
                historyRepository.write(
                    lessonId = lessonId,
                    lineId = lastLine?.id ?: "session",
                    audioPath = "session_${lessonId}_${System.currentTimeMillis()}",
                    scoreTotal = session.totalScore,
                    scorePronunciation = session.pronunciation,
                    scoreFluency = session.fluency,
                    scoreCompleteness = session.completeness
                )
            } catch (e: Exception) {
                Timber.e(e, "Failed to write history")
            }
            _state.update { it.copy(finished = true) }
        }
    }

    fun dismissError() {
        _state.update { it.copy(error = null) }
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) {
            audioRecorder.cancel()
        }
    }

    private companion object {
        const val BOOK = "nce1"
    }
}
