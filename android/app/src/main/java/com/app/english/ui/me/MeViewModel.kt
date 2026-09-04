package com.app.english.ui.me

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
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

/**
 * 我的 Tab 状态: 能力画像 + 练习概览都来自现有 `GET /stats`。
 *
 * TODO(P7, 计划 §5.6): [ability] 换成 `GET /ability?device_id=&days=7|30|90` 的
 * EWMA 画像(四维 + CEFR + 轨迹), 那时才需要 days 切换参数。
 */
data class MeUiState(
    val isLoading: Boolean = true,
    val stats: PracticeStats? = null,
    val ability: AbilityAxes = AbilityAxes.EMPTY,
    val error: String? = null
) {
    val streakDays: Int get() = stats?.streakDays ?: 0

    /** 练过但分低的课(原 Dashboard 的「推荐复习」), 挪到我的 Tab。 */
    val weakest: List<WeakestLesson>
        get() = stats?.weakestLessons ?: emptyList()
}

@HiltViewModel
class MeViewModel @Inject constructor(private val statsRepository: StatsRepository) : ViewModel() {
    private val _state = MutableStateFlow(MeUiState())
    val state: StateFlow<MeUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val stats = statsRepository.getStats()
                _state.update {
                    it.copy(
                        isLoading = false,
                        stats = stats,
                        ability = AbilityAxes.fromStats(stats)
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoading = false, error = e.message ?: "加载练习数据失败")
                }
            }
        }
    }
}
