package com.app.english.ui.vocab

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.ExpressionRepository
import com.app.english.data.repository.MistakeWordRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * 词汇 Tab 的只读状态。
 *
 * 弱词数来自本地 Room(AppDatabase v3, 冻结不动 —— 计划 §四「Room 演进」);
 * 表达库条数(P7 真实化)先读 Room 快照即时显示, 再用网络列表结果校正一次;
 * 两路都拿不到就保持 null, 入口卡不放假计数。
 */
data class VocabHubUiState(
    val isLoadingWords: Boolean = true,
    val weakWordCount: Int = 0,
    val wordsError: String? = null,
    /** 表达库条数(`GET /expressions` 全量; Room 快照先行, 网络刷新校正)。 */
    val pendingExpressions: Int? = null
)

@HiltViewModel
class VocabHubViewModel @Inject constructor(
    private val mistakeWordRepository: MistakeWordRepository,
    private val expressionRepository: ExpressionRepository
) : ViewModel() {
    private val _state = MutableStateFlow(VocabHubUiState())
    val state: StateFlow<VocabHubUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        loadWords()
        loadExpressionCount()
    }

    private fun loadWords() {
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

    /** 条数是顺路信息: 任何一路失败都安静吞掉, 不把词汇 Tab 变成报错页。 */
    private fun loadExpressionCount() {
        viewModelScope.launch {
            try {
                val cached = expressionRepository.cached()
                if (cached.isNotEmpty()) {
                    _state.update { it.copy(pendingExpressions = cached.size) }
                }
                val fresh = expressionRepository.refresh()
                _state.update { it.copy(pendingExpressions = fresh.size) }
            } catch (e: Exception) {
                Timber.w(e, "expression count failed")
            }
        }
    }
}
