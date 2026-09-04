package com.app.english.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.SceneRepository
import com.app.english.data.repository.StatsRepository
import com.app.english.data.repository.pickRecommended
import com.app.english.domain.model.PracticeStats
import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary
import com.app.english.ui.courses.SceneFilter
import dagger.hilt.android.lifecycle.HiltViewModel
import java.time.LocalTime
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 「继续学习」卡片的目标(计划 §6.3)。
 *
 * TODO(P6): 数据源是 `GET /courses/progress?device_id=` / `GET /sessions`(P2/P4
 * 落地), 取最近一条活跃的 practice_session 拼出标题 + 要回到的 stage 路由。
 * P5 没有任何数据可读, 所以这个值恒为 null, 首页整卡隐藏而不是显示一个假入口。
 */
data class ContinueLearningTarget(
    /** 卡片主文案, 例如「项目进展汇报 · 打基础 3/5」。 */
    val title: String,
    /** 要继续的课 id; 首页点这张卡走 scene_detail/{id}。 */
    val sceneId: String,
    /** 该课当前阶段(briefing / mission / review), 用于副标题。 */
    val stage: String = ""
)

data class HomeUiState(
    val greeting: String = "你好",
    val isLoadingStats: Boolean = true,
    val stats: PracticeStats? = null,
    val statsError: String? = null,
    val isLoadingScenes: Boolean = true,
    val recommended: SceneSummary? = null,
    val categories: List<SceneCategoryStat> = emptyList(),
    val sceneTotal: Int = 0,
    val scenesError: String? = null,
    val continueLearning: ContinueLearningTarget? = null
) {
    val streakDays: Int get() = stats?.streakDays ?: 0

    val hasPracticeData: Boolean get() = stats?.hasData == true

    /** 画廊分类卡: 后端给的分类(空目录时 SceneFilter 兜底四类)。 */
    val galleryCategories: List<SceneCategoryStat>
        get() = categories.ifEmpty { SceneFilter.fallbackCategories() }
}

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val statsRepository: StatsRepository,
    private val sceneRepository: SceneRepository
) : ViewModel() {
    private val _state = MutableStateFlow(
        HomeUiState(greeting = greetingLabel(LocalTime.now().hour))
    )
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    /** 两路数据各自独立加载: 画廊挂了不该把打卡/推荐一起变白屏。 */
    fun refresh() {
        loadStats()
        loadScenes()
    }

    private fun loadStats() {
        viewModelScope.launch {
            _state.update { it.copy(isLoadingStats = true, statsError = null) }
            try {
                val stats = statsRepository.getStats()
                _state.update { it.copy(isLoadingStats = false, stats = stats) }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoadingStats = false, statsError = e.message ?: "加载练习数据失败")
                }
            }
        }
    }

    private fun loadScenes() {
        viewModelScope.launch {
            _state.update { it.copy(isLoadingScenes = true, scenesError = null) }
            try {
                val catalog = sceneRepository.listScenes()
                _state.update {
                    it.copy(
                        isLoadingScenes = false,
                        recommended = catalog.scenes.pickRecommended(),
                        categories = catalog.categories,
                        sceneTotal = catalog.total
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoadingScenes = false, scenesError = e.message ?: "加载情景课失败")
                }
            }
        }
    }
}

/** 问候语按本地时间分三段(可栗首页顶部就是一句问候, 不做成固定标题)。 */
fun greetingLabel(hour: Int): String = when {
    hour < 5 -> "夜深了"
    hour < 12 -> "早上好"
    hour < 18 -> "下午好"
    else -> "晚上好"
}
