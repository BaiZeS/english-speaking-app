package com.app.english.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Live microphone level meter that grows bar-by-bar as the input amplitude
 * rises. Renders [barCount] bars sharing the full width; each bar lights up
 * when the normalized level (0..1, already dBFS-mapped by the recorder)
 * clears its threshold, and lit bars rise together with the level — so the
 * meter reads as a moving cluster, never a static row. Bars past 65% go
 * amber, past 85% red, matching the score-badge colour bands so loud peaks
 * are obvious.
 *
 * When [active] is `false` (e.g. between takes) every bar idles as a thin
 * low-alpha track in the muted surface colour.
 */
@Composable
fun RecordingLevelIndicator(
    level: Float,
    modifier: Modifier = Modifier,
    barCount: Int = 28,
    active: Boolean = true,
    maxBarHeight: Dp = 36.dp
) {
    val clamped = level.coerceIn(0f, 1f)
    // Lit bars: 35% of the track height at whisper level up to full height at
    // max — mirrors the original "bars grow with amplitude so quiet input
    // still looks alive" intent, now on the VISIBLE box instead of a spare
    // transparent one. Unlit bars stay a short 18% track.
    val litFraction = 0.35f + clamped * 0.65f
    val litHeight = maxBarHeight * litFraction
    val trackHeight = maxBarHeight * 0.18f
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(maxBarHeight),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        repeat(barCount) { index ->
            val threshold = (index + 1) / barCount.toFloat()
            val isLit = active && clamped >= threshold
            val colorScheme = MaterialTheme.colorScheme
            val (tint, alpha) = when {
                isLit && threshold > 0.85f -> colorScheme.error to 1f
                isLit && threshold > 0.65f -> colorScheme.tertiary to 1f
                isLit -> colorScheme.primary to 1f
                else -> colorScheme.surfaceVariant to 0.32f
            }
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(if (isLit) litHeight else trackHeight)
                    .clip(RoundedCornerShape(2.dp))
                    .background(tint.copy(alpha = alpha))
            )
        }
    }
}
