package com.app.english.ui.me

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.AbilityRepository
import com.app.english.data.repository.DEFAULT_ABILITY_DAYS
import com.app.english.data.repository.sanitizeAbilityDays
import com.app.english.domain.model.AbilityProfile
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

/** 画像页状态: 一次只持有一个窗口(days)的快照, 切段即重拉(§5.3 只接受 7/30/90)。 */
data class AbilityProfileUiState(
    val isLoading: Boolean = true,
    val days: Int = DEFAULT_ABILITY_DAYS,
    val profile: AbilityProfile? = null,
    val error: String? = null
)

@HiltViewModel
class AbilityProfileViewModel @Inject constructor(
    private val abilityRepository: AbilityRepository
) : ViewModel() {
    private val _state = MutableStateFlow(AbilityProfileUiState())
    val state: StateFlow<AbilityProfileUiState> = _state.asStateFlow()

    init {
        load()
    }

    fun load() {
        val days = _state.value.days
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            try {
                val profile = abilityRepository.getProfile(days)
                _state.update { it.copy(isLoading = false, profile = profile) }
            } catch (e: Exception) {
                Timber.w(e, "ability profile load failed")
                _state.update { it.copy(isLoading = false, error = e.message ?: "加载画像失败") }
            }
        }
    }

    /** 7/30/90 分段切换; 非法值在门口夹回合法窗口。 */
    fun selectDays(days: Int) {
        val sanitized = sanitizeAbilityDays(days)
        if (sanitized == _state.value.days && _state.value.profile != null) return
        _state.update { it.copy(days = sanitized) }
        load()
    }
}
