package com.app.english.ui.score

import androidx.lifecycle.ViewModel
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject

@HiltViewModel
class ScoreResultViewModel @Inject constructor(private val scoreSessionHolder: ScoreSessionHolder) :
    ViewModel() {
    val session: ScoreSession? get() = scoreSessionHolder.session
}
