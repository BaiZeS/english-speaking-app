package com.app.english.ui.theme

import androidx.compose.ui.graphics.Color
import com.app.english.domain.ScoreLevel

fun ScoreLevel.color(): Color = when (this) {
    ScoreLevel.GREEN -> ScoreGreen
    ScoreLevel.YELLOW -> ScoreYellow
    ScoreLevel.RED -> ScoreRed
}
