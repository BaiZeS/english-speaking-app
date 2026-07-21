package com.app.english.ui.score

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.withStyle
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.WordScore
import com.app.english.ui.components.formatScore
import com.app.english.ui.theme.color

@OptIn(
    ExperimentalMaterial3Api::class,
    androidx.compose.foundation.layout.ExperimentalLayoutApi::class
)
@Composable
fun ScoreResultScreen(
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ScoreResultViewModel = hiltViewModel()
) {
    val session = viewModel.session
    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("本次成绩") }) }
    ) { padding ->
        if (session == null) {
            Column(
                modifier = Modifier.padding(padding).fillMaxSize().padding(24.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center
            ) {
                Text("暂无成绩数据", style = MaterialTheme.typography.bodyLarge)
                Button(onClick = onDone, modifier = Modifier.padding(top = 16.dp)) {
                    Text("返回")
                }
            }
            return@Scaffold
        }
        LazyColumn(
            modifier = Modifier.padding(padding).fillMaxSize().padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            item { AggregateCard(session) }
            items(session.lineResults, key = { it.lineId }) { line ->
                ExpandableLineResultCard(line)
            }
            item {
                Button(
                    onClick = onDone,
                    modifier = Modifier.fillMaxWidth().padding(top = 8.dp)
                ) {
                    Text("完成")
                }
            }
        }
    }
}

@Composable
private fun AggregateCard(session: ScoreSession) {
    val level = ScoreColorMapper.level(session.totalScore)
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            Text(
                text = session.totalScore.formatScore(),
                style = MaterialTheme.typography.headlineMedium,
                color = level.color(),
                fontWeight = FontWeight.Bold
            )
            Text(
                text = "${session.lessonTitle} · 角色 ${session.roleName}",
                style = MaterialTheme.typography.titleMedium
            )
            Text(
                text = "共 ${session.lineCount} 句",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                horizontalArrangement = Arrangement.SpaceEvenly
            ) {
                SubScore("发音", session.pronunciation)
                SubScore("流利度", session.fluency)
                SubScore("完整度", session.completeness)
            }
            session.suggestion?.takeIf { it.isNotBlank() }?.let { suggestion ->
                Text(
                    text = "建议：$suggestion",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }
    }
}

@Composable
private fun SubScore(label: String, value: Double) {
    val color = ScoreColorMapper.level(value).color()
    Column(horizontalAlignment = Alignment.CenterHorizontally) {
        Text(
            text = value.formatScore(),
            style = MaterialTheme.typography.titleLarge,
            color = color,
            fontWeight = FontWeight.Bold
        )
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun ExpandableLineResultCard(line: LineScoreResult) {
    var expanded by remember { mutableStateOf(false) }
    val level = ScoreColorMapper.level(line.total)
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(
                    text = line.total.formatScore(),
                    style = MaterialTheme.typography.titleLarge,
                    color = level.color(),
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.width(48.dp)
                )
                Text(
                    text = line.text,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.weight(1f)
                )
                if (line.wordScores.isNotEmpty()) {
                    TextButton(onClick = { expanded = !expanded }) {
                        Text(if (expanded) "收起" else "查看单词")
                    }
                }
            }
            AnimatedVisibility(visible = expanded) {
                Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    HorizontalDivider(modifier = Modifier.padding(vertical = 4.dp))
                    WordScoreRow(words = line.wordScores)
                }
            }
        }
    }
}

@Composable
private fun WordScoreRow(words: List<WordScore>) {
    if (words.isEmpty()) {
        Text(
            text = "无逐词评分数据",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        return
    }
    // Wrap chips manually for fine control over colour-coded words.
    FlowRowSimple(items = words)
}

@OptIn(androidx.compose.foundation.layout.ExperimentalLayoutApi::class)
@Composable
private fun FlowRowSimple(items: List<WordScore>) {
    // Use a regular Row with line wrapping via a custom layout alternative —
    // simpler than pulling in Accompanist FlowRow.
    androidx.compose.foundation.layout.FlowRow(
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
        modifier = Modifier.fillMaxWidth()
    ) {
        items.forEach { WordChip(it) }
    }
}

@Composable
private fun WordChip(word: WordScore) {
    val level = ScoreColorMapper.level(word.score)
    Surface(
        shape = RoundedCornerShape(6.dp),
        color = level.color().copy(alpha = 0.18f),
        modifier = Modifier.padding(0.dp)
    ) {
        Column(
            modifier = Modifier.padding(horizontal = 8.dp, vertical = 4.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = colorize(word.word, level.color(), bold = word.score < 70),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurface
            )
            Text(
                text = word.score.formatScore(),
                style = MaterialTheme.typography.labelSmall,
                color = level.color()
            )
        }
    }
}

private fun colorize(text: String, color: Color, bold: Boolean): AnnotatedString =
    buildAnnotatedString {
        withStyle(
            SpanStyle(color = color, fontWeight = if (bold) FontWeight.Bold else FontWeight.Normal)
        ) {
            append(text)
        }
    }
