package com.app.english.ui.vocab

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.MistakeWordRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/**
 * 词汇 Tab 的只读状态。
 *
 * 弱词数来自本地 Room(AppDatabase v3, 冻结不动 —— 计划 §四「Room 演进」);
 * 表达库条数要等 P7 的 `GET /expressions`, 届时把 [pendingExpressions] 填上。
 */
data class VocabHubUiState(
    val isLoadingWords: Boolean = true,
    val weakWordCount: Int = 0,
    val wordsError: String? = null,
    val pendingExpressions: Int? = null
)

@HiltViewModel
class VocabHubViewModel @Inject constructor(
    private val mistakeWordRepository: MistakeWordRepository
) : ViewModel() {
    private val _state = MutableStateFlow(VocabHubUiState())
    val state: StateFlow<VocabHubUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(isLoadingWords = true, wordsError = null) }
            try {
                val words = mistakeWordRepository.list()
                _state.update {
                    it.copy(isLoadingWords = false, weakWordCount = words.size)
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isLoadingWords = false, wordsError = e.message ?: "读取错词失败")
                }
            }
        }
    }
}
