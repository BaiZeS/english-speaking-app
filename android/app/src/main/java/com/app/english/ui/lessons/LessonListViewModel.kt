package com.app.english.ui.lessons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.LessonSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface LessonListUiState {
    data object Loading : LessonListUiState
    data class Success(val lessons: List<LessonSummary>) : LessonListUiState
    data class Error(val message: String) : LessonListUiState
}

@HiltViewModel
class LessonListViewModel @Inject constructor(private val repository: EnglishRepository) :
    ViewModel() {
    private val _state = MutableStateFlow<LessonListUiState>(LessonListUiState.Loading)
    val state: StateFlow<LessonListUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = LessonListUiState.Loading
            _state.value = try {
                LessonListUiState.Success(repository.listLessons(BOOK))
            } catch (e: Exception) {
                LessonListUiState.Error(e.message ?: "加载课文列表失败")
            }
        }
    }

    private companion object {
        const val BOOK = "nce1"
    }
}
