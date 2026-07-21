package com.app.english.ui.history

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.HistoryRepository
import com.app.english.domain.model.HistoryItem
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** Top-level filter chips for the history list. Persisted across the screen lifetime. */
enum class HistoryFilter(val label: String) {
    All("全部"),
    Practiced("练过"),
    HighScore("85+"),
    NeedsWork("60 以下")
}

sealed interface HistoryListUiState {
    data object Loading : HistoryListUiState
    data class Success(
        val items: List<HistoryItem>,
        val filter: HistoryFilter = HistoryFilter.All,
        val totalCount: Int = items.size
    ) : HistoryListUiState
    data class Error(val message: String) : HistoryListUiState
}

@HiltViewModel
class HistoryListViewModel @Inject constructor(
    private val historyRepository: HistoryRepository,
    private val selectedHolder: SelectedHistoryHolder
) : ViewModel() {
    private val _state = MutableStateFlow<HistoryListUiState>(HistoryListUiState.Loading)
    val state: StateFlow<HistoryListUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = HistoryListUiState.Loading
            try {
                val items = historyRepository.list()
                _state.value = HistoryListUiState.Success(
                    items = items,
                    filter = currentFilter(),
                    totalCount = items.size
                )
            } catch (e: Exception) {
                _state.value = HistoryListUiState.Error(e.message ?: "加载历史失败")
            }
        }
    }

    fun setFilter(filter: HistoryFilter) {
        val current = _state.value
        if (current !is HistoryListUiState.Success) return
        _state.update {
            HistoryListUiState.Success(
                items = applyFilter(current.items, filter),
                filter = filter,
                totalCount = current.items.size
            )
        }
    }

    fun select(item: HistoryItem) {
        selectedHolder.item = item
    }

    private fun currentFilter(): HistoryFilter =
        (_state.value as? HistoryListUiState.Success)?.filter ?: HistoryFilter.All

    private fun applyFilter(items: List<HistoryItem>, filter: HistoryFilter): List<HistoryItem> =
        when (filter) {
            HistoryFilter.All -> items
            HistoryFilter.Practiced -> items.filter { it.scoreTotal > 0 }
            HistoryFilter.HighScore -> items.filter { it.scoreTotal >= 85 }
            HistoryFilter.NeedsWork -> items.filter { it.scoreTotal in 1.0..60.0 }
        }
}
