package com.app.english.ui.courses

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.SceneRepository
import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class CourseHubUiState(
    val segment: CourseSegment = CourseSegment.SCENES,
    val selectedCategory: String = CATEGORY_ALL_ID,
    val isLoading: Boolean = true,
    val scenes: List<SceneSummary> = emptyList(),
    val categories: List<SceneCategoryStat> = emptyList(),
    val total: Int = 0,
    val error: String? = null
) {
    /** 「全部 + 四类」的 chip 序列(计数来自后端 `categories`, 不受当前筛选影响)。 */
    val chips: List<SceneCategoryChip> get() = SceneFilter.chips(categories)

    /** 纯内存过滤: 切 chip 不再打网络, 一次拉全后本地切换。 */
    val visibleScenes: List<SceneSummary> get() = SceneFilter.apply(selectedCategory, scenes)

    val hasScenes: Boolean get() = scenes.isNotEmpty()
}

@HiltViewModel
class CourseHubViewModel @Inject constructor(private val sceneRepository: SceneRepository) :
    ViewModel() {
    private val _state = MutableStateFlow(CourseHubUiState())
    val state: StateFlow<CourseHubUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load(refresh: Boolean = false) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val catalog = sceneRepository.listScenes(refresh = refresh)
                _state.update {
                    it.copy(
                        isLoading = false,
                        scenes = catalog.scenes,
                        categories = catalog.categories,
                        total = catalog.total
                    )
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoading = false, error = e.message ?: "加载情景课失败")
                }
            }
        }
    }

    fun selectSegment(segment: CourseSegment) {
        _state.update { it.copy(segment = segment) }
    }

    fun selectCategory(categoryId: String) {
        _state.update { it.copy(selectedCategory = categoryId) }
    }

    /** 下拉/点击重试: 跳过进程内缓存重新拉一次。 */
    fun retry() = load(refresh = true)
}
