package com.app.english.ui.score

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import com.app.english.domain.ScoreColorMapper
import com.app.english.ui.components.formatScore
import com.app.english.ui.theme.color

@OptIn(ExperimentalMaterial3Api::class)
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
                LineResultCard(line)
            }
            item {
                Button(onClick = onDone, modifier = Modifier.fillMaxWidth()) {
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
private fun LineResultCard(line: LineScoreResult) {
    val level = ScoreColorMapper.level(line.total)
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = line.total.formatScore(),
                    style = MaterialTheme.typography.titleLarge,
                    color = level.color(),
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.padding(end = 12.dp)
                )
                Text(
                    text = line.text,
                    style = MaterialTheme.typography.bodyLarge
                )
            }
        }
    }
}
