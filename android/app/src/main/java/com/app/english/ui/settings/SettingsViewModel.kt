package com.app.english.ui.settings

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.LlmModel
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

data class SettingsUiState(
    val baseUrl: String = "",
    val voice: String = "",
    val availableVoices: List<String> = emptyList(),
    val llmModels: List<LlmModel> = emptyList(),
    val selectedModelId: String? = null,
    val isLoadingModels: Boolean = false,
    val llmLoadError: String? = null
)

@HiltViewModel
class SettingsViewModel @Inject constructor(
    private val settingsStore: SettingsStore,
    private val repository: EnglishRepository
) : ViewModel() {
    private val _state = MutableStateFlow(
        SettingsUiState(
            baseUrl = settingsStore.getBaseUrl(),
            voice = settingsStore.getVoice(),
            selectedModelId = settingsStore.getSelectedModelId()
        )
    )
    val state: StateFlow<SettingsUiState> = _state.asStateFlow()

    // Xunfei Spark super-natural TTS voices (US English).
    // Grant: mature female; Lila: younger female.
    val deviceId: String = settingsStore.deviceId

    private val voices: List<String> = listOf("x5_EnUs_Grant_flow", "x5_EnUs_Lila_flow")

    init {
        _state.update { it.copy(availableVoices = voices) }
        refreshLlmModels()
    }

    fun refreshLlmModels() {
        _state.update { it.copy(isLoadingModels = true, llmLoadError = null) }
        viewModelScope.launch {
            try {
                val models = repository.listLlmModels()
                val currentSelection = _state.value.selectedModelId
                // Drop stored selection if the backend stopped advertising it.
                val filtered = if (currentSelection != null &&
                    models.none { it.id == currentSelection }
                ) {
                    settingsStore.setSelectedModelId(null)
                    null
                } else {
                    currentSelection
                }
                _state.update {
                    it.copy(
                        llmModels = models,
                        selectedModelId = filtered,
                        isLoadingModels = false
                    )
                }
            } catch (e: Exception) {
                Timber.e(e, "Failed to load LLM model catalog")
                _state.update {
                    it.copy(
                        isLoadingModels = false,
                        llmLoadError = e.message ?: "无法连接到后端获取模型列表"
                    )
                }
            }
        }
    }

    fun updateBaseUrl(url: String) {
        _state.update { it.copy(baseUrl = url) }
    }

    fun updateVoice(value: String) {
        _state.update { it.copy(voice = value) }
    }

    fun selectModel(modelId: String?) {
        _state.update { it.copy(selectedModelId = modelId) }
    }

    fun save() {
        val current = _state.value
        settingsStore.setBaseUrl(current.baseUrl)
        settingsStore.setVoice(current.voice)
        settingsStore.setSelectedModelId(current.selectedModelId)
    }
}
