package com.app.english.ui.lesson

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.LessonDetail
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface LessonDetailUiState {
    data object Loading : LessonDetailUiState
    data class Success(val lesson: LessonDetail) : LessonDetailUiState
    data class Error(val message: String) : LessonDetailUiState
}

@HiltViewModel
class LessonDetailViewModel @Inject constructor(
    private val repository: EnglishRepository,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val lessonId: Int =
        requireNotNull(savedStateHandle.get<Int>(Route.LessonDetail.ARG_LESSON_ID)) {
            "lessonId argument required"
        }

    private val _state = MutableStateFlow<LessonDetailUiState>(LessonDetailUiState.Loading)
    val state: StateFlow<LessonDetailUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        viewModelScope.launch {
            _state.value = LessonDetailUiState.Loading
            _state.value = try {
                LessonDetailUiState.Success(repository.getLessonRoles(lessonId, BOOK))
            } catch (e: Exception) {
                LessonDetailUiState.Error(e.message ?: "加载课文失败")
            }
        }
    }

    private companion object {
        const val BOOK = "nce1"
    }
}
