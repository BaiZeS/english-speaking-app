package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioPlayer
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.sessionMessage
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
    /**
     * 本课最近一场**打完了**的会话(§P6 客户端 9)。它是那份复盘报告唯一回得去的路:
     * [resuming] 只查 active, 所以收工之后回到这里, 旧会话在客户端是隐形的, 而主按钮
     * 会直接开一局新课。入口的显隐与主按钮的措辞都归 [ReviewEntryPolicy] 判。
     */
    val lastCompleted: ContinueSession? = null,
    val isStarting: Boolean = false,
    val error: String? = null,
    val playingText: String? = null
) {
    /** 主按钮标签: 「继续学习」/「再练一次（新开一局）」/「开始学习」。 */
    val startLabel: String
        get() = ReviewEntryPolicy.startLabelOf(resuming != null, lastCompleted != null)

    /** 是否摆出「查看上次复盘」。 */
    val showReviewEntry: Boolean
        get() = ReviewEntryPolicy.showReviewEntry(lastCompleted != null)
}

/**
 * 课程详情页(计划 §6.4 SceneDetailScreen): 词汇卡横滑可播 + 三段进度 +
 * 任务预览 + 「开始学习」; 进页先查最近 active 会话, 有则续跑, 否则 create。
 *
 * §P6 之后这里查**两类**会话: active(续跑)与 completed(回看上次复盘)。后者是那份报告
 * 唯一回得去的路 —— 只查 active 时, 收工后回到本页旧会话根本不存在, 而唯一的按钮会开一局
 * 新课。显隐与措辞见 [ReviewEntryPolicy]。
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
                // 第二次列表查的是"练完的那一场"。它失败同样只丢一个入口, 不拖垮详情页 ——
                // 但**不能**复用上面那次 try: 两类的 status 值不同, 一次请求拿不到两种。
                val completed = try {
                    ReviewEntryPolicy.latestCompletedSession(
                        sessionRepository.list(status = ReviewEntryPolicy.STATUS_COMPLETED),
                        sceneId
                    )
                } catch (_: Exception) {
                    null
                }
                _state.update {
                    it.copy(
                        isLoading = false,
                        course = course,
                        resuming = active,
                        lastCompleted = completed
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoading = false, error = e.sessionMessage("加载课程失败"))
                }
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
                _state.update {
                    it.copy(isStarting = false, error = e.sessionMessage("开课失败"))
                }
            }
        }
    }

    /**
     * 「查看上次复盘」(§P6 客户端 9): **直接**跳复盘页, 不经 MissionScreen。
     *
     * 不经 MissionScreen 是有原因的: 进那一页需要一条 active 会话, 而这一场已经
     * `completed` —— 从那里绕过去只会再撞一次"报告回不去"。复盘页自己用
     * `GET /sessions/{id}` 取快照, 该端点不按 status 过滤。
     */
    fun viewLastReview(onOpenReview: (String) -> Unit) {
        _state.value.lastCompleted?.let { onOpenReview(it.sessionId) }
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
