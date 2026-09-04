package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioPlayer
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.GenerateRepository
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.ContinueSession
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class SceneDetailUiState(
    val isLoading: Boolean = true,
    val course: SceneCourseDetail? = null,
    /** 最近一场 active 会话(有 = 可以续跑, 无 = 开新局)。 */
    val resuming: ContinueSession? = null,
    val isStarting: Boolean = false,
    val error: String? = null,
    val playingText: String? = null
)

/**
 * 课程详情页(计划 §6.4 SceneDetailScreen): 词汇卡横滑可播 + 三段进度 +
 * 任务预览 + 「开始学习」; 进页先查最近 active 会话, 有则续跑, 否则 create。
 */
@HiltViewModel
class SceneDetailViewModel @Inject constructor(
    private val generateRepository: GenerateRepository,
    private val sessionRepository: SessionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sceneId: String = savedStateHandle.get<String>(Route.SceneDetail.ARG_SCENE_ID).orEmpty()

    private val _state = MutableStateFlow(SceneDetailUiState())
    val state: StateFlow<SceneDetailUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                // 详情网络成功即落 course_cache 快照(生成课离线可看), 见 GenerateRepository。
                val course = generateRepository.getScene(sceneId)
                val active = try {
                    sessionRepository.list(status = "active").firstOrNull { it.sceneId == sceneId }
                } catch (_: Exception) {
                    null // 续跑探测失败不该把详情页打挂, 退化为「开新局」。
                }
                _state.update {
                    it.copy(isLoading = false, course = course, resuming = active)
                }
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.message ?: "加载课程失败") }
            }
        }
    }

    /** 开始/继续学习: 有 active 会话按 stage 续跑, 否则先 create 再进打基础。 */
    fun startLearning(onOpenBriefing: (String) -> Unit, onOpenMission: (String) -> Unit) {
        val current = _state.value
        if (current.isStarting) return
        current.resuming?.let { resume ->
            if (resume.unlockedMission || resume.stage == "mission") {
                onOpenMission(resume.sessionId)
            } else {
                onOpenBriefing(resume.sessionId)
            }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(isStarting = true, error = null) }
            try {
                val snapshot = sessionRepository.create(sceneId)
                _state.update { it.copy(isStarting = false) }
                onOpenBriefing(snapshot.sessionId)
            } catch (e: Exception) {
                _state.update { it.copy(isStarting = false, error = e.message ?: "开课失败") }
            }
        }
    }

    /** 词汇卡/例句点击播放: /tts 的 stub 响应同样带 URL, 照常播(失败静默)。 */
    fun playSpeech(text: String) {
        if (_state.value.playingText != null) return
        viewModelScope.launch {
            _state.update { it.copy(playingText = text) }
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) {
                    _state.update { it.copy(playingText = null) }
                }
            } catch (_: Exception) {
                _state.update { it.copy(playingText = null) }
            }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
    }
}
