package com.app.english.ui.lesson

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.LessonProgress
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

sealed interface LessonDetailUiState {
    data object Loading : LessonDetailUiState
    data class Success(val lesson: LessonDetail, val progress: LessonProgress? = null) :
        LessonDetailUiState
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
            try {
                val lesson = repository.getLessonRoles(lessonId, BOOK)
                _state.value = LessonDetailUiState.Success(lesson)
                loadProgressInBackground()
            } catch (e: Exception) {
                _state.value = LessonDetailUiState.Error(e.message ?: "加载课文失败")
            }
        }
    }

    /**
     * Fetch the user's progress for this lesson in a fire-and-forget child
     * coroutine. The screen stays responsive while we wait (the lesson
     * detail itself is already rendered). If the endpoint errors out, the
     * Success state keeps `progress = null` and the UI hides the badge.
     */
    private fun loadProgressInBackground() {
        viewModelScope.async {
            val progress = runCatching { repository.getLessonProgress(lessonId) }.getOrNull()
            val current = _state.value
            if (current is LessonDetailUiState.Success) {
                _state.value = current.copy(progress = progress)
            }
        }
    }

    private companion object {
        const val BOOK = "nce1"
    }
}
