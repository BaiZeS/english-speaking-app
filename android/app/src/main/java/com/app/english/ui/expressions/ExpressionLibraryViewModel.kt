package com.app.english.ui.expressions

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioPlayer
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.ExpressionRepository
import com.app.english.domain.model.ExpressionEntry
import com.app.english.domain.model.PolishOutcome
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

data class ExpressionLibraryUiState(
    val isLoading: Boolean = true,
    val entries: List<ExpressionEntry> = emptyList(),
    /** 当前列表来自 Room 快照(网络挂了的降级呈现)。 */
    val fromCache: Boolean = false,
    val isPolishing: Boolean = false,
    val snackbar: String? = null,
    val error: String? = null
)

/**
 * 个人表达库(计划 §5.7): 离线可读 + 网络刷新 + 「+」润色任意句。
 *
 * 读路径两拍: 先把 Room `expressions_cache` 快照顶上去(离线可读), 再强制走
 * 网络刷新; 网络失败时快照就是最终呈现(fromCache=true), 不再报错白屏。
 */
@HiltViewModel
class ExpressionLibraryViewModel @Inject constructor(
    private val expressionRepository: ExpressionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioPlayer: AudioPlayer
) : ViewModel() {
    private val _state = MutableStateFlow(ExpressionLibraryUiState())
    val state: StateFlow<ExpressionLibraryUiState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = it.entries.isEmpty(), error = null) }
            try {
                val cached = expressionRepository.cached()
                if (cached.isNotEmpty()) {
                    _state.update { it.copy(entries = cached, fromCache = true, isLoading = false) }
                }
                val fresh = expressionRepository.refresh()
                _state.update {
                    it.copy(
                        isLoading = false,
                        entries = fresh,
                        fromCache = false,
                        error = null
                    )
                }
            } catch (e: Exception) {
                Timber.w(e, "expression refresh failed")
                _state.update { current ->
                    current.copy(
                        isLoading = false,
                        // 有缓存 = 已经在展示快照, 只提示离线; 连缓存都没有才是真错误。
                        error = if (current.entries.isEmpty()) {
                            e.message ?: "加载表达库失败"
                        } else {
                            null
                        },
                        snackbar = if (current.entries.isNotEmpty()) {
                            "网络不可用, 正在显示离线缓存"
                        } else {
                            null
                        }
                    )
                }
            }
        }
    }

    /** 「+」对任意一句 POST /polish(collect=true), 真出了对照就进表达库。 */
    fun polishAndCollect(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || _state.value.isPolishing) return
        viewModelScope.launch {
            _state.update { it.copy(isPolishing = true) }
            try {
                val outcome = expressionRepository.polishAndCollect(trimmed)
                _state.update { it.copy(isPolishing = false, snackbar = polishMessage(outcome)) }
                refresh()
            } catch (e: Exception) {
                Timber.w(e, "polish failed")
                _state.update {
                    it.copy(isPolishing = false, snackbar = "润色失败, 请稍后再试")
                }
            }
        }
    }

    fun delete(entry: ExpressionEntry) {
        viewModelScope.launch {
            try {
                expressionRepository.delete(entry.id)
                _state.update { it.copy(snackbar = "已删除") }
                refresh()
            } catch (e: Exception) {
                Timber.w(e, "expression delete failed")
                _state.update { it.copy(snackbar = "删除失败, 请稍后再试") }
            }
        }
    }

    fun play(entry: ExpressionEntry) {
        viewModelScope.launch {
            try {
                val tts = englishRepository.getTtsAudio(entry.polished, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) { }
            } catch (e: Exception) {
                Timber.w(e, "expression tts failed")
                _state.update { it.copy(snackbar = "语音播放失败") }
            }
        }
    }

    fun consumeSnackbar() = _state.update { it.copy(snackbar = null) }

    private fun polishMessage(outcome: PolishOutcome): String = when {
        outcome.hasPolish && outcome.expressionId != null -> "已润色并收进表达库"
        outcome.hasPolish -> "已润色: ${outcome.polish?.polished}"
        outcome.noteCn.isNotBlank() -> outcome.noteCn
        else -> "这句没有值得改的地方"
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
    }
}
