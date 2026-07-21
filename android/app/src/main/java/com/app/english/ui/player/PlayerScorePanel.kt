package com.app.english.ui.player

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.theme.color

/**
 * Score panel that appears after a recording is submitted.
 *
 * Shows the overall score, the three sub-skill averages, an "I need to re-record"
 * hint if the score is below the advancement threshold, the LLM-generated
 * suggestion, and per-word score chips.
 */

/** Top-level score card: big number, sub-skills, suggestion, word chips. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScorePanel(score: ScoreResult, needsRerecord: Boolean, modifier: Modifier = Modifier) {
    val level = ScoreColorMapper.level(score.total)
    Card(modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = score.total.toInt().toString(),
                    style = MaterialTheme.typography.headlineMedium,
                    color = level.color(),
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(end = 12.dp)
                )
                Text(text = "总分", style = MaterialTheme.typography.titleMedium)
            }
            SubScoreRow(score.pronunciation, score.fluency, score.completeness)
            if (needsRerecord) {
                Text(
                    text = "得分低于 60，请重录一次后再继续。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error
                )
            }
            score.suggestion?.takeIf { it.isNotBlank() }?.let { suggestion ->
                Text(
                    text = "建议：$suggestion",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (score.wordDetails.isNotEmpty()) {
                Text("单词得分", style = MaterialTheme.typography.titleMedium)
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(8.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    score.wordDetails.forEach { wordScore ->
                        WordChip(
                            word = wordScore.word,
                            scoreColor = ScoreColorMapper.level(wordScore.score).color()
                        )
                    }
                }
            }
        }
    }
}

/** Three-pill row showing pronunciation / fluency / completeness. */
@Composable
fun SubScoreRow(
    pronunciation: Double,
    fluency: Double,
    completeness: Double,
    modifier: Modifier = Modifier
) {
    Row(modifier = modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        SubScorePill("发音", pronunciation, Modifier.weight(1f))
        SubScorePill("流利度", fluency, Modifier.weight(1f))
        SubScorePill("完整度", completeness, Modifier.weight(1f))
    }
}

/** Single sub-skill pill: big number tinted by its band + small label. */
@Composable
fun SubScorePill(label: String, value: Double, modifier: Modifier = Modifier) {
    val color = ScoreColorMapper.level(value).color()
    Column(modifier = modifier.padding(4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = value.toInt().toString(),
            style = MaterialTheme.typography.titleLarge,
            color = color,
            fontWeight = FontWeight.Bold
        )
        Text(
            label,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/** Tiny pill showing a single word + a coloured dot for its band. */
@Composable
fun WordChip(word: String, scoreColor: Color, modifier: Modifier = Modifier) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = modifier.padding(horizontal = 4.dp, vertical = 2.dp)
    ) {
        Box(modifier = Modifier.size(10.dp).background(scoreColor, CircleShape))
        Spacer(Modifier.width(6.dp))
        Text(
            word,
            style = MaterialTheme.typography.bodyMedium,
            color = scoreColor,
            fontWeight = FontWeight.SemiBold
        )
    }
}
