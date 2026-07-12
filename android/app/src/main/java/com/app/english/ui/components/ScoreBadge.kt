package com.app.english.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.ScoreLevel
import com.app.english.ui.theme.color

/**
 * A pill that shows a numeric score tinted by its feedback band (spec §5.3).
 */
@Composable
fun ScoreBadge(score: Double, modifier: Modifier = Modifier) {
    val level = ScoreColorMapper.level(score)
    ScoreBadge(level = level, text = score.formatScore(), modifier = modifier)
}

@Composable
fun ScoreBadge(level: ScoreLevel, text: String, modifier: Modifier = Modifier) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(12.dp))
            .background(level.color())
            .padding(horizontal = 12.dp, vertical = 6.dp),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = text,
            color = Color.White,
            fontWeight = FontWeight.Bold,
            style = MaterialTheme.typography.labelLarge
        )
    }
}

fun Double.formatScore(): String = "${this.toInt()}"
