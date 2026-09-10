package com.app.english.ui.drill

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.audio.RecordingStore
import com.app.english.data.local.MistakeWordEntity
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.MistakeWordRepository
import com.app.english.domain.model.ScoreResult
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

/** A word graduates from the drill once it scores at least this. */
private const val GRADUATE_SCORE = 85.0
private const val DRILL_MODE = "drill"
private const val DRILL_LINE_PREFIX = "drill-"
private const val STUB_TTS_ERROR = "标准发音未配置（后端缺 MIMO_API_KEY）"

data class MistakeDrillUiState(
    val isLoading: Boolean = true,
    val words: List<MistakeWordEntity> = emptyList(),
    val currentIndex: Int = 0,
    val isPlayingDemo: Boolean = false,
    val isRecording: Boolean = false,
    val isSubmitting: Boolean = false,
    val lastScore: ScoreResult? = null,
    val graduatedWord: String? = null,
    val error: String? = null,
    val finished: Boolean = false
) {
    val currentWord: MistakeWordEntity? get() = words.getOrNull(currentIndex)
}

@HiltViewModel
class MistakeDrillViewModel @Inject constructor(
    private val repository: EnglishRepository,
    private val mistakeWordRepository: MistakeWordRepository,
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val recordingStore: RecordingStore,
    private val settingsStore: SettingsStore
) : ViewModel() {
    private val _state = MutableStateFlow(MistakeDrillUiState())
    val state: StateFlow<MistakeDrillUiState> = _state.asStateFlow()

    /**
     * 滚动波形窗口, 由 `AudioRecorder.waveformFlow` 喂(**未平滑**的逐帧峰值: VU 那条
     * `levelFlow` 的包络 ~440 ms 才回落, 画波形会把音节糊成一坨)。单词练只有一根根
     * 短促的条, 正是最能体现"原始帧"价值的地方。不复制进 [MistakeDrillUiState]: 那是
     * 25 Hz 的整屏重组; 收工也不在这里清 —— 毕业判定与评分那几秒学员还在看自己刚念
     * 的那个词。
     */
    val waveform: StateFlow<List<Float>> get() = audioRecorder.waveformFlow

    init {
        loadWords()
    }

    private fun loadWords() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            _state.value = try {
                val words = mistakeWordRepository.list()
                MistakeDrillUiState(isLoading = false, words = words)
            } catch (e: Exception) {
                _state.value.copy(isLoading = false, error = e.message ?: "加载弱词失败")
            }
        }
    }

    fun playDemo() {
        val word = _state.value.currentWord ?: return
        val current = _state.value
        if (current.isPlayingDemo || current.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingDemo = true, error = null) }
            try {
                val tts = repository.getTtsAudio(word.word, settingsStore.getVoice())
                if (tts.isStub) {
                    _state.update { it.copy(isPlayingDemo = false, error = STUB_TTS_ERROR) }
                    return@launch
                }
                audioPlayer.play(tts.audioUrl) {
                    _state.update { current -> current.copy(isPlayingDemo = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingDemo = false, error = "标准音播放失败：${e.message}")
                }
            }
        }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.isSubmitting) return
        // 乐观翻位: 录音态在点击同一帧立住, 慢的硬件启动在协程里追。
        _state.update { it.copy(isRecording = true, lastScore = null, error = null) }
        viewModelScope.launch {
            try {
                audioRecorder.start(
                    maxDurationMs = AudioRecorder.MAX_TAKE_MS,
                    onAutoStop = ::stopAndScore
                )
            } catch (e: Exception) {
                _state.update {
                    it.copy(isRecording = false, error = "录音启动失败：${e.message}")
                }
            }
        }
    }

    fun stopAndScore() {
        val current = _state.value
        val word = current.currentWord ?: return
        if (!current.isRecording) return
        viewModelScope.launch {
            // 波形刻意不动: 评分那几秒这条形状还得留在屏上(见 waveform)。
            _state.update { it.copy(isRecording = false, isSubmitting = true) }
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
                return@launch
            }
            val lineId = "$DRILL_LINE_PREFIX${word.word}"
            val saved = retainRecording(word, lineId, file)
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                if (saved != null) file.delete()
                val result = repository.score(
                    lessonId = null,
                    lineId = null,
                    refText = word.word,
                    audioBase64 = base64,
                    mode = DRILL_MODE,
                    category = "read_word"
                )
                if (result.total >= GRADUATE_SCORE) {
                    graduate(word.word)
                    val remaining = _state.value.words.filterNot { it.word == word.word }
                    _state.update {
                        it.copy(
                            isSubmitting = false,
                            words = remaining,
                            // 末位词毕业时索引会越界, 收敛到新的末位
                            currentIndex = it.currentIndex.coerceAtMost(remaining.lastIndex),
                            lastScore = null,
                            graduatedWord = word.word,
                            finished = remaining.isEmpty()
                        )
                    }
                } else {
                    _state.update { it.copy(isSubmitting = false, lastScore = result) }
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = "评分失败：${e.message}") }
            }
        }
    }

    fun next() = advance()

    fun skip() = advance()

    private fun advance() {
        val state = _state.value
        if (state.isRecording || state.isSubmitting) return
        audioPlayer.stop()
        if (state.currentIndex >= state.words.lastIndex) {
            _state.update { it.copy(finished = true) }
        } else {
            _state.update {
                it.copy(
                    currentIndex = it.currentIndex + 1,
                    lastScore = null,
                    isPlayingDemo = false,
                    error = null
                )
            }
        }
    }

    private suspend fun graduate(word: String) {
        try {
            mistakeWordRepository.graduate(word)
        } catch (e: Exception) {
            Timber.w(e, "Failed to graduate mistake word")
        }
    }

    private suspend fun retainRecording(
        word: MistakeWordEntity,
        lineId: String,
        file: File
    ): File? = try {
        withContext(Dispatchers.IO) {
            recordingStore.saveRecording(word.book, word.lessonId, lineId, file)
        }
    } catch (e: Exception) {
        Timber.w(e, "Failed to retain drill recording")
        null
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    fun dismissGraduated() = _state.update { it.copy(graduatedWord = null) }

    /** 生命周期兜底: ON_STOP 时停+评分(宁发不丢)。 */
    fun stopRecordingIfActive() {
        if (_state.value.isRecording) stopAndScore()
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }
}
