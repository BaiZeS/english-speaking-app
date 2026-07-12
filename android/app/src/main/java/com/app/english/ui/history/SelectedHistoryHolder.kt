package com.app.english.ui.history

import com.app.english.domain.model.HistoryItem
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class SelectedHistoryHolder @Inject constructor() {
    var item: HistoryItem? = null
}
