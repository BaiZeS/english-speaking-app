package com.app.english.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.Line
import com.app.english.ui.components.RecordingLevelIndicator
import com.app.english.ui.theme.color

/**
 * Composable fragments for the shadowing (整段影子跟读) practice mode.
 *
 * Shadowing plays the whole lesson's reference audio line by line while the
 * user reads along continuously; after playback the recording is sliced and
 * scored per line. The transcript highlights the line that is playing and,
 * once scoring finishes, shows each line's score.
 */

/** Shadow practice pane: transcript, level meter, start/stop and progress. */
@Composable
fun PlayerShadowView(
    state: PlayerUiState,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxWidth(),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text(
            text = "连续播放整段标准音，请全程跟读；播放结束后自动按句切片评分。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        ShadowTranscript(
            lines = state.lines,
            currentIndex = state.shadowCurrentIndex,
            isPlaying = state.isRecording,
            lineScores = state.lineScores
        )
        if (!micGranted) PermissionHint(onRequestPermission = onRequestPermission)
        RecordingLevelIndicator(
            level = state.micLevel,
            active = state.isRecording,
            modifier = Modifier.fillMaxWidth()
        )
        ShadowControlButton(
            state = state,
            micGranted = micGranted,
            onRequestPermission = onRequestPermission,
            onStart = onStart,
            onStop = onStop
        )
        if (state.isPreparingShadow) {
            ShadowProgressRow("正在准备标准音...")
        }
        if (state.isSubmitting && state.shadowScoreTotal > 0) {
            ShadowProgressRow("评分中 ${state.shadowScoredCount}/${state.shadowScoreTotal}")
        }
    }
}

/** Full lesson transcript; the playing line is highlighted, scores appear after. */
@Composable
fun ShadowTranscript(
    lines: List<Line>,
    currentIndex: Int,
    isPlaying: Boolean,
    lineScores: List<ScoredLine>,
    modifier: Modifier = Modifier
) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("整段课文", style = MaterialTheme.typography.titleMedium)
            lines.forEachIndexed { index, line ->
                val current = isPlaying && index == currentIndex
                val scored = lineScores.firstOrNull { it.line.id == line.id }
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .background(
                            if (current) {
                                MaterialTheme.colorScheme.primaryContainer
                            } else {
                                Color.Transparent
                            },
                            MaterialTheme.shapes.small
                        )
                        .padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically
                ) {
                    Text(
                        text = line.text,
                        style = if (current) {
                            MaterialTheme.typography.bodyLarge
                        } else {
                            MaterialTheme.typography.bodyMedium
                        },
                        fontWeight = if (current) FontWeight.Bold else FontWeight.Normal,
                        color = if (current) {
                            MaterialTheme.colorScheme.onSurface
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.weight(1f)
                    )
                    scored?.let { item ->
                        Text(
                            text = item.result.total.toInt().toString(),
                            style = MaterialTheme.typography.labelLarge,
                            color = ScoreColorMapper.level(item.result.total).color(),
                            fontWeight = FontWeight.Bold,
                            modifier = Modifier.padding(start = 8.dp)
                        )
                    }
                }
            }
        }
    }
}

/** Start / stop toggle for a shadowing run, disabled while preparing/scoring. */
@Composable
private fun ShadowControlButton(
    state: PlayerUiState,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier
) {
    when {
        state.isPreparingShadow || state.isSubmitting -> Button(
            onClick = {},
            modifier = modifier.fillMaxWidth(),
            enabled = false
        ) { Text(if (state.isSubmitting) "评分中..." else "准备中...") }
        state.isRecording -> Button(
            onClick = onStop,
            modifier = modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
        ) {
            Icon(Icons.Filled.Stop, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("停止并评分")
        }
        else -> Button(
            onClick = { if (micGranted) onStart() else onRequestPermission() },
            modifier = modifier.fillMaxWidth()
        ) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("开始影子跟读")
        }
    }
}

/** Spinner + status line shown while preparing the run or scoring slices. */
@Composable
private fun ShadowProgressRow(text: String, modifier: Modifier = Modifier) {
    Row(modifier = modifier, verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(8.dp))
        Text(text, style = MaterialTheme.typography.bodyMedium)
    }
}
