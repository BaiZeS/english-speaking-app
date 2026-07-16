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
import com.app.english.domain.model.LessonDetail
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
private const val RECENT_SENTENCE_COUNT = 5

data class PracticeTurn(val role: String, val line: Line, val isUserTurn: Boolean)
data class ScoredLine(val line: Line, val result: ScoreResult)

data class PlayerUiState(
    val isLoading: Boolean = true,
    val mode: PlayerMode = PlayerMode.READ_ALONG,
    val lessonTitle: String = "",
    val roleName: String = "",
    /** Lines the user must read. In dialogue mode these are role B's lines. */
    val lines: List<Line> = emptyList(),
    /** Complete interleaved transcript used by dialogue mode. */
    val conversation: List<PracticeTurn> = emptyList(),
    /** Role A's prompt corresponding to each user line in dialogue mode. */
    val prompts: List<Line?> = emptyList(),
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
    val currentPrompt: Line? get() = prompts.getOrNull(currentIndex)
    val isLastLine: Boolean get() = currentIndex >= lines.lastIndex
    val canAdvance: Boolean
        get() = currentScore != null && (currentScore.total >= MIN_SCORE_TO_ADVANCE || hasRetaken)

    /** The most recent five sentences, with the current sentence at the end. */
    val recentLines: List<Line>
        get() {
            val end = (currentIndex + 1).coerceAtMost(lines.size)
            val start = (end - RECENT_SENTENCE_COUNT).coerceAtLeast(0)
            return lines.subList(start, end)
        }
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
    private val mode = PlayerMode.fromWire(savedStateHandle.get<String>(Route.Player.ARG_MODE))

    private val _state = MutableStateFlow(PlayerUiState(mode = mode))
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
                val resolved = resolvePractice(lesson)
                if (resolved.lines.isEmpty()) {
                    _state.value.copy(
                        isLoading = false,
                        error = if (mode == PlayerMode.DIALOGUE) {
                            "这篇课文暂时没有可练习的角色 B 台词"
                        } else {
                            "这篇课文暂时没有可练习的句子"
                        }
                    )
                } else {
                    PlayerUiState(
                        isLoading = false,
                        mode = mode,
                        lessonTitle = lesson.title,
                        roleName = resolved.responseRole,
                        lines = resolved.lines,
                        conversation = resolved.conversation,
                        prompts = resolved.prompts
                    )
                }
            } catch (e: Exception) {
                _state.value.copy(isLoading = false, error = e.message ?: "加载课文失败")
            }
        }
    }

    private data class ResolvedPractice(
        val responseRole: String,
        val lines: List<Line>,
        val prompts: List<Line?>,
        val conversation: List<PracticeTurn>
    )

    private fun resolvePractice(lesson: LessonDetail): ResolvedPractice = when (mode) {
        PlayerMode.READ_ALONG -> {
            val ordered = interleaveRoles(lesson).flatMap(::splitSentences)
            ResolvedPractice(
                responseRole = "",
                lines = ordered,
                prompts = List(ordered.size) { null },
                conversation = ordered.map { PracticeTurn("", it, true) }
            )
        }
        PlayerMode.DIALOGUE -> {
            val assistant = lesson.roles.getOrNull(0)
            val user = lesson.roles.getOrNull(1)
            val assistantName = assistant?.name.orEmpty()
            val userName = user?.name.orEmpty()
            val userLines = user?.lines.orEmpty()
            val prompts = userLines.mapIndexed { index, _ -> assistant?.lines?.getOrNull(index) }
            val transcript = buildList {
                val count = maxOf(assistant?.lines?.size ?: 0, userLines.size)
                repeat(count) { index ->
                    assistant?.lines?.getOrNull(index)?.let {
                        add(PracticeTurn(assistantName, it, false))
                    }
                    userLines.getOrNull(index)?.let {
                        add(PracticeTurn(userName, it, true))
                    }
                }
            }
            ResolvedPractice(
                responseRole = user?.name.orEmpty(),
                lines = userLines,
                prompts = prompts,
                conversation = transcript
            )
        }
        // Free dialogue has its own screen and ViewModel.
        PlayerMode.FREE_DIALOGUE -> ResolvedPractice("", emptyList(), emptyList(), emptyList())
    }

    /** Split a corpus line into speakable sentences without reintroducing role labels. */
    private fun splitSentences(line: Line): List<Line> {
        val parts = line.text
            .split(SENTENCE_BOUNDARY)
            .map(String::trim)
            .filter(String::isNotEmpty)
        if (parts.size <= 1) return listOf(line)
        return parts.mapIndexed { index, text ->
            line.copy(id = "${line.id}-s${index + 1}".take(64), text = text)
        }
    }

    /** Preserve the dialogue order while removing role labels for read-along. */
    private fun interleaveRoles(lesson: LessonDetail): List<Line> = buildList {
        val count = lesson.roles.maxOfOrNull { it.lines.size } ?: 0
        repeat(count) { index ->
            lesson.roles.forEach { role -> role.lines.getOrNull(index)?.let(::add) }
        }
    }

    fun playReference() {
        val state = _state.value
        val line = state.currentPrompt ?: state.currentLine ?: return
        if (state.isPlayingReference || state.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingReference = true, error = null) }
            try {
                val url = repository.getTtsAudioUrl(line.text, settingsStore.getVoice())
                audioPlayer.play(url) {
                    _state.update { current -> current.copy(isPlayingReference = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "标准音播放失败：${e.message}")
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
                _state.update { it.copy(error = "录音启动失败：${e.message}") }
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
                val result = repository.score(
                    lessonId = lessonId,
                    lineId = line.id,
                    refText = line.text,
                    audioBase64 = base64,
                    mode = mode.wire
                )
                _state.update { current ->
                    val withoutCurrent = current.lineScores.filterNot { it.line.id == line.id }
                    current.copy(
                        isSubmitting = false,
                        currentScore = result,
                        lineScores = withoutCurrent + ScoredLine(line, result)
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = "评分失败：${e.message}") }
            } finally {
                file.delete()
            }
        }
    }

    fun nextLine() {
        val state = _state.value
        if (state.isRecording || state.isSubmitting || !state.canAdvance) return
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
                historyRepository.write(
                    lessonId = lessonId,
                    lineId = state.currentLine?.id ?: "session",
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

    fun dismissError() = _state.update { it.copy(error = null) }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }

    private companion object {
        val SENTENCE_BOUNDARY = Regex("(?<=[.!?。！？])\\s+")
        const val BOOK = "nce1"
    }
}
