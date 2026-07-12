package com.app.english.ui.history

import androidx.lifecycle.ViewModel
import com.app.english.domain.model.HistoryItem
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class HistoryDetailViewModel @Inject constructor(
    private val selectedHolder: SelectedHistoryHolder
) : ViewModel() {
    val item: HistoryItem? get() = selectedHolder.item
}
