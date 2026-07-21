package com.app.english.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp

/**
 * Composable fragments for the dialogue (角色对话) practice mode.
 *
 * Dialogue shows the full A/B transcript with the active line highlighted,
 * and a separate "Role A's current prompt" card with a one-tap play button.
 * The user reads Role B's line, gets scored, then advances.
 */

/** Card with the full A/B conversation, current line highlighted. */
@Composable
fun DialogueTranscript(
    conversation: List<PracticeTurn>,
    currentLineId: String,
    modifier: Modifier = Modifier
) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("完整对话", style = MaterialTheme.typography.titleMedium)
            conversation.forEach { turn ->
                val current = turn.line.id == currentLineId
                Column(
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
                        .padding(10.dp)
                ) {
                    Text(
                        text = "角色 ${turn.role}" + if (turn.isUserTurn) " · 你" else "",
                        style = MaterialTheme.typography.labelMedium,
                        color = if (turn.isUserTurn) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        }
                    )
                    Text(text = turn.line.text, style = MaterialTheme.typography.bodyLarge)
                }
            }
        }
    }
}

/** Highlighted card showing Role A's prompt + a play button. */
@Composable
fun PromptCard(
    role: String,
    text: String,
    isPlaying: Boolean,
    onPlay: () -> Unit,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Column(Modifier.padding(14.dp)) {
            Text(role, style = MaterialTheme.typography.labelLarge)
            Text(
                text,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(top = 4.dp)
            )
            OutlinedButton(
                onClick = onPlay,
                enabled = !isPlaying,
                modifier = Modifier.padding(top = 8.dp)
            ) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null)
                Spacer(Modifier.width(6.dp))
                Text(if (isPlaying) "播放中..." else "播放角色 A")
            }
        }
    }
}
