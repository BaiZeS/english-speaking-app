package com.app.english.ui.player

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.app.english.domain.model.Line

/**
 * Composable fragments for the read-along practice mode.
 *
 * Read-along shows the last five sentences (so the user has context) plus the
 * one they're supposed to read, with its IPA and translation. The card order
 * mirrors the practice flow: "this is where you are" → "this is what to read".
 */

/** Card showing the last few sentences plus the active one for context. */
@Composable
fun RecentSentenceList(
    lines: List<Line>,
    currentLineId: String,
    completedCount: Int,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("最近五句", style = MaterialTheme.typography.titleMedium)
            Text(
                text = if (completedCount == 0) "从第一句开始" else "已完成 $completedCount 句，继续保持",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            lines.forEachIndexed { index, sentence ->
                val current = sentence.id == currentLineId
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = if (current) "▶" else "✓",
                        color = if (current) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.tertiary
                        },
                        modifier = Modifier.width(28.dp)
                    )
                    Text(
                        text = sentence.text,
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
                        }
                    )
                }
                if (index != lines.lastIndex) {
                    Spacer(Modifier.padding(top = 1.dp))
                }
            }
        }
    }
}

/** Headline + source text + IPA + translation for the line the user reads. */
@Composable
fun LineHeader(
    title: String,
    text: String,
    ipa: String?,
    translation: String?,
    modifier: Modifier = Modifier
) {
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(
                text = title,
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.primary
            )
            Text(
                text = text,
                style = MaterialTheme.typography.headlineSmall,
                modifier = Modifier.padding(top = 4.dp)
            )
            ipa?.takeIf { it.isNotBlank() }?.let { ipaStr ->
                Text(
                    text = "/$ipaStr/",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 6.dp)
                )
            }
            translation?.takeIf { it.isNotBlank() }?.let { translationStr ->
                Text(
                    text = translationStr,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 6.dp)
                )
            }
        }
    }
}
