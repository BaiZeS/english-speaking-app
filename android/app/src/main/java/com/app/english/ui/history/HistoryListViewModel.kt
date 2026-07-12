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
import kotlinx.coroutines.launch

sealed interface HistoryListUiState {
    data object Loading : HistoryListUiState
    data class Success(val items: List<HistoryItem>) : HistoryListUiState
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
            _state.value = try {
                HistoryListUiState.Success(historyRepository.list())
            } catch (e: Exception) {
                HistoryListUiState.Error(e.message ?: "加载历史失败")
            }
        }
    }

    fun select(item: HistoryItem) {
        selectedHolder.item = item
    }
}
