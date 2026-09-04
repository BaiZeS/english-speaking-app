package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioPlayer
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.ReviewReportData
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

data class ReviewUiState(
    val isLoading: Boolean = true,
    val report: ReviewReportData? = null,
    val course: SceneCourseDetail? = null,
    val error: String? = null,
    val isPlayingLine: Boolean = false
)

/**
 * 复盘报告页(计划 §6.4 ReviewScreen): 总分圆环 + 4 维条 + ability_delta +
 * checklist + 原话对照 + new_tokens + 参考剧本可播。数据来自
 * `GET /sessions/{id}` 的 `review` 分区(崩溃恢复也不必重算)。
 */
@HiltViewModel
class ReviewViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sessionId: String =
        savedStateHandle.get<String>(Route.SceneReview.ARG_SESSION_ID).orEmpty()

    private val _state = MutableStateFlow(ReviewUiState())
    val state: StateFlow<ReviewUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val snapshot = sessionRepository.get(sessionId)
                val report = snapshot.review
                _state.update {
                    it.copy(
                        isLoading = false,
                        report = report,
                        course = snapshot.course,
                        error = if (report == null) "本场还没有复盘报告 (实战未收工)" else null
                    )
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.message ?: "加载复盘失败") }
            }
        }
    }

    /** 参考剧本台词播放(stub URL 照常播, 失败静默)。 */
    fun playLine(text: String) {
        if (_state.value.isPlayingLine || text.isBlank()) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingLine = true) }
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) {
                    _state.update { s -> s.copy(isPlayingLine = false) }
                }
            } catch (e: Exception) {
                Timber.w(e, "review tts failed")
                _state.update { it.copy(isPlayingLine = false) }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
    }
}
