package com.app.english.ui.me

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.AbilityRepository
import com.app.english.data.repository.DEFAULT_ABILITY_DAYS
import com.app.english.data.repository.StatsRepository
import com.app.english.domain.model.PracticeStats
import com.app.english.domain.model.WeakestLesson
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * 我的 Tab 状态: 能力画像(`GET /ability`, P7 起) + 练习概览(`GET /stats`)。
 *
 * 两路并行、各自降级: 画像挂了雷达退回 [AbilityAxes.fromStats] 的练习聚合分,
 * 统计挂了画像照常 —— 任何一路失败都不该把整页变白。
 */
data class MeUiState(
    val isLoading: Boolean = true,
    val stats: PracticeStats? = null,
    val ability: AbilityAxes = AbilityAxes.EMPTY,
    /** 权威 CEFR 徽章值(`GET /ability` 的 cefr_level, 测评前 null)。 */
    val cefrLevel: String? = null,
    /** §5.2 锁带: 测评后四维等级最多 ±1 档浮动。 */
    val bandLocked: Boolean = false,
    /** 是否已经测评过(测评过 → 首页引导卡隐藏、画像卡显示完整入口)。 */
    val assessed: Boolean = false,
    val error: String? = null
) {
    val streakDays: Int get() = stats?.streakDays ?: 0

    /** 练过但分低的课(原 Dashboard 的「推荐复习」), 挪到我的 Tab。 */
    val weakest: List<WeakestLesson>
        get() = stats?.weakestLessons ?: emptyList()

    /** 画像是否已经拿到过真数据(统计路不应再用 fromStats 覆盖它)。 */
    val hasProfileEvidence: Boolean get() = ability.hasAnyEvidence
}

@HiltViewModel
class MeViewModel @Inject constructor(
    private val statsRepository: StatsRepository,
    private val abilityRepository: AbilityRepository
) : ViewModel() {
    private val _state = MutableStateFlow(MeUiState())
    val state: StateFlow<MeUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        loadStats()
        loadAbility()
    }

    private fun loadStats() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val stats = statsRepository.getStats()
                _state.update { current ->
                    current.copy(
                        isLoading = false,
                        stats = stats,
                        // 画像还没回来/没有真证据时, 才用练习聚合分画「不完整」雷达。
                        ability = if (current.hasProfileEvidence || current.assessed) {
                            current.ability
                        } else {
                            AbilityAxes.fromStats(stats)
                        }
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoading = false, error = e.message ?: "加载练习数据失败")
                }
            }
        }
    }

    private fun loadAbility() {
        viewModelScope.launch {
            try {
                val profile = abilityRepository.getProfile(DEFAULT_ABILITY_DAYS)
                _state.update {
                    it.copy(
                        ability = AbilityAxes.fromProfile(profile),
                        cefrLevel = profile.cefrLevel,
                        bandLocked = profile.bandLocked,
                        assessed = profile.isAssessed
                    )
                }
            } catch (e: Exception) {
                Timber.w(e, "ability profile load failed")
                // 画像挂了不挡统计: 雷达保留 fromStats 的降级形状。
            }
        }
    }
}
