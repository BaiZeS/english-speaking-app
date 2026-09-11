package com.app.english.ui.home

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.AbilityRepository
import com.app.english.data.repository.DEFAULT_ABILITY_DAYS
import com.app.english.data.repository.SceneRepository
import com.app.english.data.repository.SessionRepository
import com.app.english.data.repository.StatsRepository
import com.app.english.data.repository.pickTodayScene
import com.app.english.domain.model.AbilityProfile
import com.app.english.domain.model.ContinueSession
import com.app.english.domain.model.PracticeStats
import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary
import com.app.english.ui.courses.SceneFilter
import com.app.english.ui.scenes.ReviewEntryPolicy
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
 * 数据源是 `GET /sessions`(P4 落地), 取最近一条活跃的 practice_session 拼出
 * 标题 + 要回到的 stage 路由; 没有数据时整卡隐藏而不是显示一个假入口。
 */
data class ContinueLearningTarget(
    /** 卡片主文案, 例如「项目进展汇报 · 打基础 3/5」。 */
    val title: String,
    /** 要继续的课 id; 首页点这张卡走 scene_detail/{id}。 */
    val sceneId: String,
    /** 该课当前阶段(briefing / mission / review), 用于副标题。 */
    val stage: String = ""
)

/**
 * 「最近复盘」的目标(§P6 客户端 9): 最近一场**打完了**的练习 + 那份报告的会话 id。
 *
 * 与 [ContinueLearningTarget] 分开是因为走的路**根本不同**: 后者按 sceneId 回详情页
 * 接着练, 前者按 sessionId 直达复盘页。把两件事塞进一个目标, 迟早有人拿 sessionId
 * 去拼 `scene_detail/{id}` —— 那正是报告回不去的原状。
 */
data class RecentReviewTarget(
    /** 复盘页的句柄: `GET /sessions/{id}` 不按 status 过滤, completed 照常可读。 */
    val sessionId: String,
    val title: String
)

data class HomeUiState(
    val greeting: String = "你好",
    val isLoadingStats: Boolean = true,
    val stats: PracticeStats? = null,
    val statsError: String? = null,
    val isLoadingScenes: Boolean = true,
    /** 画廊全量摘要; [recommended] 按「画像最低维 → skills 匹配」从它里挑。 */
    val scenes: List<SceneSummary> = emptyList(),
    val categories: List<SceneCategoryStat> = emptyList(),
    val sceneTotal: Int = 0,
    val scenesError: String? = null,
    val continueLearning: ContinueLearningTarget? = null,
    /** 最近一场打完了的练习(§P6): 收工后回到首页也能找回那份总评。 */
    val recentReview: RecentReviewTarget? = null,
    /** 画像最低维(pronunciation/grammar/vocabulary/fluency); 空画像 = null。 */
    val weakestDimension: String? = null,
    /** 是否已经测评过(测评过 → 首页「未测评引导」卡隐藏)。 */
    val assessed: Boolean = false
) {
    val streakDays: Int get() = stats?.streakDays ?: 0

    val hasPracticeData: Boolean get() = stats?.hasData == true

    /**
     * 今日推荐: 最低维匹配场景 skills, 匹配不上/空画像走 curated 第 1 课兜底
     * (pickTodayScene)。画像路挂了 weakestDimension 就是 null, 走兜底不白屏。
     */
    val recommended: SceneSummary? get() = scenes.pickTodayScene(weakestDimension)

    /** 画廊分类卡: 后端给的分类(空目录时 SceneFilter 兜底四类)。 */
    val galleryCategories: List<SceneCategoryStat>
        get() = categories.ifEmpty { SceneFilter.fallbackCategories() }
}

@HiltViewModel
class HomeViewModel @Inject constructor(
    private val statsRepository: StatsRepository,
    private val sceneRepository: SceneRepository,
    private val sessionRepository: SessionRepository,
    private val abilityRepository: AbilityRepository
) : ViewModel() {
    private val _state = MutableStateFlow(
        HomeUiState(greeting = greetingLabel(LocalTime.now().hour))
    )
    val state: StateFlow<HomeUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    /** 各路数据独立加载: 画廊/画像挂了不该把打卡/推荐一起变白屏。 */
    fun refresh() {
        loadStats()
        loadScenes()
        loadContinueLearning()
        loadRecentReview()
        loadAbility()
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
                        scenes = catalog.scenes,
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

    /**
     * 「继续学习」(计划 §6.3): GET /sessions?status=active 最近一场; 接口挂了
     * 整卡隐藏, 不放假入口。
     */
    private fun loadContinueLearning() {
        viewModelScope.launch {
            try {
                val latest = sessionRepository.list(status = "active").firstOrNull()
                _state.update {
                    it.copy(
                        continueLearning = latest?.let { session ->
                            ContinueLearningTarget(
                                title = session.toCardTitle(),
                                sceneId = session.sceneId,
                                stage = session.stage
                            )
                        }
                    )
                }
            } catch (_: Exception) {
                _state.update { it.copy(continueLearning = null) }
            }
        }
    }

    /**
     * 「最近复盘」(§P6 客户端 9): `GET /sessions?status=completed` 的第一条(服务端按
     * `last_active_at` 倒序)。与「继续学习」是**两条独立**的请求 —— 两类 status 一次拿不到,
     * 而这一路失败只该丢一个入口, 不该拖累另一张卡。
     *
     * 为什么必须有这张卡: 收工之后复盘页是唯一入口, 而它是**一次性**跳转(从实战页跳过去)。
     * 学员要是中途退回首页或杀了 App, 那份已经落库的总评在客户端就没有任何入口了 ——
     * 首页原来的「继续学习」只查 active, 详情页的主按钮会直接开一局新课。
     */
    private fun loadRecentReview() {
        viewModelScope.launch {
            try {
                val completed = sessionRepository.list(
                    status = ReviewEntryPolicy.STATUS_COMPLETED
                )
                val latest = ReviewEntryPolicy.latestCompletedSession(completed)
                _state.update {
                    it.copy(
                        recentReview = latest?.let { row ->
                            RecentReviewTarget(sessionId = row.sessionId, title = row.title)
                        }
                    )
                }
            } catch (_: Exception) {
                // 与「继续学习」同纪律: 拿不到就整卡隐藏, 不放假入口。
                _state.update { it.copy(recentReview = null) }
            }
        }
    }

    /**
     * 画像快照(计划 §6.3): 「未测评引导」卡的显隐 + 今日推荐的最低维匹配。
     * 接口挂了按未测评处理(引导卡照常显示), 不因画像路失败丢入口。
     */
    private fun loadAbility() {
        viewModelScope.launch {
            try {
                val profile: AbilityProfile =
                    abilityRepository.getProfile(DEFAULT_ABILITY_DAYS)
                _state.update {
                    it.copy(
                        weakestDimension = profile.weakestDimension(),
                        assessed = profile.isAssessed
                    )
                }
            } catch (_: Exception) {
                _state.update { it.copy(assessed = false, weakestDimension = null) }
            }
        }
    }
}

/** 卡片副标题: 打基础显示步数进度, 实战直接说人话。 */
private fun ContinueSession.toCardTitle(): String = when (stage) {
    "mission" -> "$title · 实战对话"
    else -> "$title · 打基础 $doneSteps/$totalSteps"
}

/** 问候语按本地时间分三段(可栗首页顶部就是一句问候, 不做成固定标题)。 */
fun greetingLabel(hour: Int): String = when {
    hour < 5 -> "夜深了"
    hour < 12 -> "早上好"
    hour < 18 -> "下午好"
    else -> "晚上好"
}
