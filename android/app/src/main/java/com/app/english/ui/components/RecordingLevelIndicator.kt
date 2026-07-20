package com.app.english.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Live microphone level meter that grows bar-by-bar as the input amplitude
 * rises. Renders [barCount] thin vertical bars; each bar lights up when the
 * normalized level (0..1) clears its threshold. Bars past 65% go amber, past
 * 85% red — same colour bands as the score badge so loud peaks are obvious.
 *
 * When [active] is `false` (e.g. between takes) the meter renders flat in
 * the muted surface colour.
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
    Row(
        modifier = modifier
            .fillMaxWidth()
            .height(maxBarHeight),
        horizontalArrangement = Arrangement.spacedBy(2.dp),
        verticalAlignment = androidx.compose.ui.Alignment.CenterVertically
    ) {
        repeat(barCount) { index ->
            val threshold = (index + 1) / barCount.toFloat()
            val isLit = active && clamped >= threshold
            val tint = when {
                !isLit -> MaterialTheme.colorScheme.surfaceVariant
                threshold > 0.85f -> MaterialTheme.colorScheme.error
                threshold > 0.65f -> MaterialTheme.colorScheme.tertiary
                else -> MaterialTheme.colorScheme.primary
            }
            // Bars grow slightly with amplitude so quiet input still looks "alive".
            val litHeight = (maxBarHeight.value * (0.35 + clamped * 0.65)).dp
            val dimHeight = (maxBarHeight.value * 0.18).dp
            Box(
                modifier = Modifier
                    .weight(1f)
                    .fillMaxHeight()
                    .width(2.dp)
                    .clip(RoundedCornerShape(2.dp))
                    .background(tint.copy(alpha = if (isLit) 1f else 0.45f))
            ) {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(if (isLit) litHeight else dimHeight)
                        .align(androidx.compose.ui.Alignment.Center)
                        .clip(RoundedCornerShape(2.dp))
                        .background(Color.Transparent)
                )
            }
        }
    }
}
