package com.app.english.ui.settings

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.app.english.data.local.SettingsStore
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class SettingsViewModel @Inject constructor(private val settingsStore: SettingsStore) :
    ViewModel() {
    var baseUrl by mutableStateOf(settingsStore.getBaseUrl())
        private set
    var voice by mutableStateOf(settingsStore.getVoice())
        private set
    val deviceId: String = settingsStore.deviceId

    // Xunfei Spark super-natural TTS voices (US English).
    // Grant: mature female; Lila: younger female.
    val availableVoices: List<String> = listOf("x5_EnUs_Grant_flow", "x5_EnUs_Lila_flow")

    fun updateBaseUrl(url: String) {
        baseUrl = url
    }

    fun updateVoice(value: String) {
        voice = value
    }

    fun save() {
        settingsStore.setBaseUrl(baseUrl)
        settingsStore.setVoice(voice)
    }
}
