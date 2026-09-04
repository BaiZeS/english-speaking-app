package com.app.english.ui.player

import android.net.Uri
import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.audio.RecordingStore
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.HistoryRepository
import com.app.english.data.repository.MistakeWordRepository
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.Line
import com.app.english.domain.model.ScoreResult
import com.app.english.domain.model.TtsAudio
import com.app.english.ui.navigation.Route
import com.app.english.ui.score.LineScoreResult
import com.app.english.ui.score.ScoreSession
import com.app.english.ui.score.ScoreSessionHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

private const val MIN_SCORE_TO_ADVANCE = 60.0
private const val RECENT_SENTENCE_COUNT = 5

// Shadow mode (整段连续影子跟读) timing. Reference lines play back to back
// with SHADOW_GAP_MS silence between them; the recording is later sliced at
// each line boundary with SHADOW_PRE/POST_GUARD_MS of context on both sides.
private const val SHADOW_GAP_MS = 500L
private const val SHADOW_TAIL_MS = 1000L
private const val SHADOW_PRE_GUARD_MS = 300L
private const val SHADOW_POST_GUARD_MS = 300L
private const val SHADOW_MIN_SLICE_MS = 300L
private const val COMPARE_GAP_MS = 500L
private const val SHADOW_ROLE_LABEL = "影子跟读"
private const val SHADOW_HISTORY_LINE_ID = "shadow-session"
private const val SHADOW_STUB_TTS_ERROR =
    "标准发音未配置（后端缺 MIMO_API_KEY），无法进行影子跟读"

/** Raw PCM L16 16kHz mono = 32000 bytes/sec = 32 bytes/ms. */
private const val PCM_BYTES_PER_MS = 32

/** Score assigned to a shadow line whose slice is too short to evaluate. */
private val ZERO_LINE_SCORE = ScoreResult(
    total = 0.0,
    pronunciation = 0.0,
    fluency = 0.0,
    completeness = 0.0,
    wordDetails = emptyList(),
    suggestion = null,
    source = "xunfei"
)

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
    val micLevel: Float = 0f,
    val currentScore: ScoreResult? = null,
    val lineScores: List<ScoredLine> = emptyList(),
    val hasRetaken: Boolean = false,
    val error: String? = null,
    val finished: Boolean = false,
    /** Shadow mode: prefetching the per-line reference TTS before playback. */
    val isPreparingShadow: Boolean = false,
    /** Shadow mode: index of the reference line currently playing (-1 = idle). */
    val shadowCurrentIndex: Int = -1,
    /** Shadow mode: per-line scoring progress after playback ends. */
    val shadowScoredCount: Int = 0,
    val shadowScoreTotal: Int = 0,
    /** WAV path of the retained recording for the current line, if any. */
    val lastRecordingPath: String? = null
) {
    val currentLine: Line? get() = lines.getOrNull(currentIndex)
    val currentPrompt: Line? get() = prompts.getOrNull(currentIndex)
    val isLastLine: Boolean get() = currentIndex >= lines.lastIndex
    val canAdvance: Boolean
        get() = currentScore != null && (currentScore.total >= MIN_SCORE_TO_ADVANCE || hasRetaken)

    /** The line-by-line progress bar applies only to read-along and dialogue. */
    val showsLineProgress: Boolean
        get() = mode == PlayerMode.READ_ALONG || mode == PlayerMode.DIALOGUE

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
    private val mistakeWordRepository: MistakeWordRepository,
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val recordingStore: RecordingStore,
    private val settingsStore: SettingsStore,
    private val scoreSessionHolder: ScoreSessionHolder,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val lessonId: Int = requireNotNull(savedStateHandle.get<Int>(Route.Player.ARG_LESSON_ID)) {
        "lessonId argument required"
    }
    val book: String = savedStateHandle.get<String>(Route.Player.ARG_BOOK) ?: "nce1"
    private val mode = PlayerMode.fromWire(savedStateHandle.get<String>(Route.Player.ARG_MODE))

    private val _state = MutableStateFlow(PlayerUiState(mode = mode))
    val state: StateFlow<PlayerUiState> = _state.asStateFlow()

    /** Shadow mode: playback start offset (ms) of each line within the run. */
    private var shadowBoundaryMs = LongArray(0)

    /** Shadow mode: reference duration (ms) of each line, parallel to lines. */
    private var shadowDurationMs = emptyList<Long>()

    init {
        loadLesson()
        viewModelScope.launch {
            audioRecorder.levelFlow.collect { level ->
                _state.update { it.copy(micLevel = level) }
            }
        }
    }

    fun reload() = loadLesson()

    private fun loadLesson() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            _state.value = try {
                val lesson = repository.getLessonRoles(lessonId, book)
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
        PlayerMode.SHADOW -> {
            // Shadow the entire lesson: every line of every role, in order,
            // WITHOUT sentence-splitting so line ids and TTS durations map
            // 1:1 onto the recording slices. The user reads every line.
            val ordered = interleaveRoles(lesson)
            ResolvedPractice(
                responseRole = "",
                lines = ordered,
                prompts = List(ordered.size) { null },
                conversation = ordered.map { PracticeTurn("", it, true) }
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
                val tts = repository.getTtsAudio(line.text, settingsStore.getVoice())
                if (tts.isStub) {
                    _state.update {
                        it.copy(
                            isPlayingReference = false,
                            error = "标准发音未配置（后端缺 MIMO_API_KEY），当前无真实示范音频"
                        )
                    }
                    return@launch
                }
                audioPlayer.play(tts.audioUrl) {
                    _state.update { current -> current.copy(isPlayingReference = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "标准音播放失败：${e.message}")
                }
            }
        }
    }

    /** Plays the retained recording of the current line ("听我的"). */
    fun playMyRecording() {
        val path = _state.value.lastRecordingPath ?: return
        if (_state.value.isPlayingReference || _state.value.isRecording) return
        _state.update { it.copy(isPlayingReference = true, error = null) }
        audioPlayer.play(Uri.fromFile(File(path)).toString()) {
            _state.update { current -> current.copy(isPlayingReference = false) }
        }
    }

    /** Plays the reference TTS then the user's take back to back ("对比听"). */
    fun playComparison() {
        val current = _state.value
        val path = current.lastRecordingPath ?: return
        val line = current.currentLine ?: return
        if (current.isPlayingReference || current.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingReference = true, error = null) }
            try {
                val tts = repository.getTtsAudio(line.text, settingsStore.getVoice())
                if (tts.isStub) {
                    _state.update {
                        it.copy(
                            isPlayingReference = false,
                            error = "标准发音未配置（后端缺 MIMO_API_KEY），当前无真实示范音频"
                        )
                    }
                    return@launch
                }
                audioPlayer.playSequence(
                    items = listOf(tts.audioUrl, Uri.fromFile(File(path)).toString()),
                    gapMs = COMPARE_GAP_MS,
                    onComplete = {
                        _state.update { it.copy(isPlayingReference = false) }
                    }
                )
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "对比播放失败：${e.message}")
                }
            }
        }
    }

    fun startRecording() {
        _state.update { it.copy(micLevel = 0f) }
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
            val saved = retainRecording(line.id, file)
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                if (saved != null) file.delete()
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
                        lastRecordingPath = saved?.absolutePath,
                        lineScores = withoutCurrent + ScoredLine(line, result)
                    )
                }
                collectMistakeWords(line.id, result)
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = "评分失败：${e.message}") }
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
                    lastRecordingPath = null,
                    isPlayingReference = false,
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
            // 任一句走了 stub 就整体标记为 stub, 成绩页显示警示.
            source = if (scores.any { it.result.isStub }) "stub" else "xunfei",
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
                    book = book,
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

    /**
     * Starts a whole-lesson shadowing run: prefetches the reference TTS of
     * every line (aborts if any is a stub), then plays the lesson line by
     * line while recording the user continuously. The UI should confirm the
     * headphone hint before calling this.
     */
    fun startShadow() {
        val current = _state.value
        if (mode != PlayerMode.SHADOW) return
        if (current.isPreparingShadow || current.isRecording || current.isSubmitting) return
        if (current.lines.isEmpty()) return
        viewModelScope.launch {
            _state.update { it.copy(isPreparingShadow = true, error = null) }
            val references = mutableListOf<TtsAudio>()
            try {
                current.lines.forEach { line ->
                    val tts = repository.getTtsAudio(line.text, settingsStore.getVoice())
                    if (tts.isStub) {
                        _state.update {
                            it.copy(isPreparingShadow = false, error = SHADOW_STUB_TTS_ERROR)
                        }
                        return@launch
                    }
                    references += tts
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPreparingShadow = false, error = "标准发音加载失败：${e.message}")
                }
                return@launch
            }
            beginShadowPlayback(references)
        }
    }

    /** Stops a shadowing run early; whatever was recorded still gets scored. */
    fun stopShadow() {
        if (mode != PlayerMode.SHADOW || !_state.value.isRecording) return
        audioPlayer.stop()
        viewModelScope.launch { finishShadowRecording() }
    }

    private fun beginShadowPlayback(references: List<TtsAudio>) {
        val lines = _state.value.lines
        shadowDurationMs = references.map { it.durationMs.toLong() }
        shadowBoundaryMs = shadowBoundaries(shadowDurationMs, SHADOW_GAP_MS)
        try {
            audioRecorder.start(echoCancel = true)
        } catch (e: Exception) {
            _state.update {
                it.copy(isPreparingShadow = false, error = "录音启动失败：${e.message}")
            }
            return
        }
        _state.update {
            it.copy(
                isPreparingShadow = false,
                isRecording = true,
                shadowCurrentIndex = 0,
                shadowScoredCount = 0,
                shadowScoreTotal = lines.size,
                currentScore = null,
                lineScores = emptyList()
            )
        }
        audioPlayer.playSequence(
            items = references.map { it.audioUrl },
            gapMs = SHADOW_GAP_MS,
            onIndex = { index -> _state.update { it.copy(shadowCurrentIndex = index) } },
            onComplete = {
                // Keep recording briefly past the last line so the user's
                // final word is not cut off.
                viewModelScope.launch {
                    delay(SHADOW_TAIL_MS)
                    finishShadowRecording()
                }
            }
        )
    }

    private suspend fun finishShadowRecording() {
        if (!_state.value.isRecording) return
        _state.update {
            it.copy(isRecording = false, isSubmitting = true, shadowScoredCount = 0)
        }
        audioPlayer.stop()
        val file = audioRecorder.stop()
        if (file == null || !file.exists()) {
            _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
            return
        }
        val scored = scoreShadowSlices(file)
        file.delete()
        if (scored != null) finishShadowSession(scored)
    }

    /** Slices the shadow recording per line and scores each slice in order. */
    private suspend fun scoreShadowSlices(file: File): List<ScoredLine>? {
        val lines = _state.value.lines
        val pcm = withContext(Dispatchers.IO) { file.readBytes() }
        val minSliceBytes = SHADOW_MIN_SLICE_MS * PCM_BYTES_PER_MS
        val scored = mutableListOf<ScoredLine>()
        try {
            lines.forEachIndexed { index, line ->
                val slice = shadowSlice(pcm, shadowBoundaryMs, shadowDurationMs, index)
                val result = if (slice.size < minSliceBytes) {
                    // Nothing usable was recorded for this line: count it as
                    // missed instead of asking the backend to score silence.
                    ZERO_LINE_SCORE
                } else {
                    val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(slice) }
                    val sliceResult = repository.score(
                        lessonId = lessonId,
                        lineId = line.id,
                        refText = line.text,
                        audioBase64 = base64,
                        mode = mode.wire
                    )
                    collectMistakeWords(line.id, sliceResult)
                    sliceResult
                }
                scored += ScoredLine(line, result)
                _state.update { it.copy(shadowScoredCount = index + 1) }
            }
        } catch (e: Exception) {
            _state.update { it.copy(isSubmitting = false, error = "评分失败：${e.message}") }
            return null
        }
        return scored
    }

    /** Aggregates the per-line shadow scores exactly like [finish] does. */
    private fun finishShadowSession(scored: List<ScoredLine>) {
        val current = _state.value
        val session = ScoreSession(
            lessonTitle = current.lessonTitle,
            roleName = SHADOW_ROLE_LABEL,
            totalScore = scored.map { it.result.total }.average(),
            pronunciation = scored.map { it.result.pronunciation }.average(),
            fluency = scored.map { it.result.fluency }.average(),
            completeness = scored.map { it.result.completeness }.average(),
            suggestion = scored.mapNotNull { it.result.suggestion }.lastOrNull(),
            // 任一句走了 stub 就整体标记为 stub, 成绩页显示警示.
            source = if (scored.any { it.result.isStub }) "stub" else "xunfei",
            lineCount = scored.size,
            lineResults = scored.map { item ->
                LineScoreResult(
                    lineId = item.line.id,
                    text = item.line.text,
                    total = item.result.total,
                    wordScores = item.result.wordDetails
                )
            }
        )
        scoreSessionHolder.session = session
        viewModelScope.launch {
            try {
                historyRepository.write(
                    book = book,
                    lessonId = lessonId,
                    lineId = SHADOW_HISTORY_LINE_ID,
                    audioPath = "shadow_${System.currentTimeMillis()}",
                    scoreTotal = session.totalScore,
                    scorePronunciation = session.pronunciation,
                    scoreFluency = session.fluency,
                    scoreCompleteness = session.completeness
                )
            } catch (e: Exception) {
                Timber.e(e, "Failed to write shadow history")
            }
            _state.update {
                it.copy(isSubmitting = false, lineScores = scored, finished = true)
            }
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
    }
}

/** boundary[i] = start offset (ms) of line i = sum of earlier durations + gaps. */
private fun shadowBoundaries(durationMs: List<Long>, gapMs: Long): LongArray {
    val boundaries = LongArray(durationMs.size)
    var cursor = 0L
    durationMs.forEachIndexed { index, duration ->
        boundaries[index] = cursor
        cursor += duration + gapMs
    }
    return boundaries
}

/**
 * Recording window of line [index]: from [SHADOW_PRE_GUARD_MS] before its
 * playback start until [SHADOW_POST_GUARD_MS] past its end (the following
 * [SHADOW_GAP_MS] gap is included so a slightly late speaker is covered),
 * clamped to the bytes actually recorded.
 */
private fun shadowSlice(
    pcm: ByteArray,
    boundaryMs: LongArray,
    durationMs: List<Long>,
    index: Int
): ByteArray {
    val totalMs = pcm.size.toLong() / PCM_BYTES_PER_MS
    val startMs = (boundaryMs[index] - SHADOW_PRE_GUARD_MS).coerceIn(0, totalMs)
    val endMs =
        (boundaryMs[index] + durationMs[index] + SHADOW_GAP_MS + SHADOW_POST_GUARD_MS)
            .coerceIn(startMs, totalMs)
    val from = (startMs * PCM_BYTES_PER_MS).toInt()
    val to = (endMs * PCM_BYTES_PER_MS).toInt()
    return pcm.copyOfRange(from, to)
}
