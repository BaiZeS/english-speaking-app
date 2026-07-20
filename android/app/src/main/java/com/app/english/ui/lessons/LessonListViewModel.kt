package com.app.english.ui.lessons

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.BooksRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.Book
import com.app.english.domain.model.LessonSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch

data class LessonListUiData(
    val books: List<Book> = emptyList(),
    val selectedBookId: String = "",
    val lessons: List<LessonSummary> = emptyList(),
    val isLoadingBooks: Boolean = false,
    val isLoadingLessons: Boolean = false,
    val error: String? = null
) {
    val isLoading: Boolean get() = isLoadingBooks || isLoadingLessons
    val selectedBook: Book? get() = books.firstOrNull { it.id == selectedBookId }
}

@HiltViewModel
class LessonListViewModel @Inject constructor(
    private val booksRepository: BooksRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore
) : ViewModel() {
    private val _state = MutableStateFlow(LessonListUiData(isLoadingLessons = true))
    val state: StateFlow<LessonListUiData> = _state.asStateFlow()

    init {
        loadBooks()
    }

    fun loadBooks() {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoadingBooks = true, error = null)
            try {
                val books = booksRepository.listBooks()
                if (books.isEmpty()) {
                    _state.value = _state.value.copy(
                        books = emptyList(),
                        isLoadingBooks = false,
                        error = "暂无可用课本，请稍后再试"
                    )
                    return@launch
                }
                val storedBookId = settingsStore.getSelectedBookId()
                val selected = storedBookId?.takeIf { id -> books.any { it.id == id } }
                    ?: books.first().id
                if (selected != storedBookId) {
                    settingsStore.setSelectedBookId(selected)
                }
                _state.value = _state.value.copy(
                    books = books,
                    selectedBookId = selected,
                    isLoadingBooks = false
                )
                loadLessonsFor(selected)
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    isLoadingBooks = false,
                    error = e.message ?: "加载课本列表失败"
                )
            }
        }
    }

    fun selectBook(bookId: String) {
        if (bookId == _state.value.selectedBookId) return
        settingsStore.setSelectedBookId(bookId)
        _state.value = _state.value.copy(selectedBookId = bookId, lessons = emptyList())
        loadLessonsFor(bookId)
    }

    fun retry() {
        if (_state.value.books.isEmpty()) {
            loadBooks()
        } else {
            loadLessonsFor(
                _state.value.selectedBookId
            )
        }
    }

    private fun loadLessonsFor(bookId: String) {
        viewModelScope.launch {
            _state.value = _state.value.copy(isLoadingLessons = true, error = null)
            try {
                val lessons = englishRepository.listLessons(bookId)
                _state.value = _state.value.copy(lessons = lessons, isLoadingLessons = false)
            } catch (e: Exception) {
                _state.value = _state.value.copy(
                    isLoadingLessons = false,
                    error = e.message ?: "加载课文失败"
                )
            }
        }
    }
}
