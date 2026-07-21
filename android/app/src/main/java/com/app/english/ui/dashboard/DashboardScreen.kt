package com.app.english.ui.dashboard

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Bolt
import androidx.compose.material.icons.filled.EmojiEvents
import androidx.compose.material.icons.filled.LocalFireDepartment
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material.icons.filled.TrendingUp
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.DailyScore
import com.app.english.domain.model.PracticeStats
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.theme.color

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onHistoryClick: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: DashboardViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("练习概览") },
                actions = {
                    IconButton(onClick = viewModel::refresh) {
                        Icon(Icons.Filled.Refresh, contentDescription = "刷新")
                    }
                }
            )
        }
    ) { padding ->
        when {
            state.isLoading && state.stats == null -> LoadingState(Modifier.padding(padding))
            state.error != null && state.stats == null -> ErrorState(
                message = state.error ?: "加载失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::refresh
            )
            state.stats != null -> DashboardBody(
                stats = state.stats!!,
                onHistoryClick = onHistoryClick,
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun DashboardBody(
    stats: PracticeStats,
    onHistoryClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        if (!stats.hasData) {
            EmptyDashboard()
            return@Column
        }
        TopStatsRow(stats = stats)
        StreakCard(streakDays = stats.streakDays, recentSessions = stats.recentSessions)
        TrendCard(daily = stats.daily)
        SubjectBreakdownCard(stats = stats)
        Card(
            modifier = Modifier.fillMaxWidth(),
            onClick = onHistoryClick,
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.tertiaryContainer
            )
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)
            ) {
                Text(
                    text = "查看练习历史",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
                Text(
                    text = "已记录 ${stats.totalSessions} 次练习",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
            }
        }
    }
}

@Composable
private fun TopStatsRow(stats: PracticeStats) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        StatTile(
            modifier = Modifier.weight(1f),
            label = "总练习",
            value = "${stats.totalSessions}",
            sub = "次",
            icon = Icons.Filled.Bolt
        )
        StatTile(
            modifier = Modifier.weight(1f),
            label = "平均分",
            value = stats.avgTotal.toInt().toString(),
            sub = "/100",
            valueColor = ScoreColorMapper.level(stats.avgTotal).color(),
            icon = Icons.Filled.TrendingUp
        )
        StatTile(
            modifier = Modifier.weight(1f),
            label = "最高分",
            value = stats.bestTotal.toInt().toString(),
            sub = "/100",
            valueColor = ScoreColorMapper.level(stats.bestTotal).color(),
            icon = Icons.Filled.EmojiEvents
        )
    }
}

@Composable
private fun StatTile(
    label: String,
    value: String,
    sub: String,
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    modifier: Modifier = Modifier,
    valueColor: Color? = null
) {
    Card(modifier = modifier) {
        Column(
            modifier = Modifier.padding(14.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = icon,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.size(16.dp)
                )
                Box(Modifier.size(4.dp))
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Row(verticalAlignment = Alignment.Bottom) {
                Text(
                    text = value,
                    style = MaterialTheme.typography.headlineMedium,
                    color = valueColor ?: MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = sub,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = 2.dp, bottom = 6.dp)
                )
            }
        }
    }
}

@Composable
private fun StreakCard(streakDays: Int, recentSessions: Int) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Icon(
                imageVector = Icons.Filled.LocalFireDepartment,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onSecondaryContainer,
                modifier = Modifier.size(36.dp)
            )
            Box(Modifier.size(12.dp))
            Column(Modifier.weight(1f)) {
                Text(
                    text = if (streakDays > 0) "已连续练习 $streakDays 天" else "今日还没练习",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
                Text(
                    text = "近 7 天完成 $recentSessions 次",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSecondaryContainer
                )
            }
        }
    }
}

@Composable
private fun TrendCard(daily: List<DailyScore>) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "近 14 天分数趋势",
                style = MaterialTheme.typography.titleMedium
            )
            if (daily.isEmpty()) {
                Text(
                    text = "暂无近期数据",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            } else {
                TrendChart(daily = daily)
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    horizontalArrangement = Arrangement.SpaceBetween
                ) {
                    Text(
                        text = daily.first().date.takeLast(5),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = daily.last().date.takeLast(5),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun TrendChart(daily: List<DailyScore>) {
    val color = MaterialTheme.colorScheme.primary
    val grid = MaterialTheme.colorScheme.outlineVariant
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(120.dp)
            .padding(vertical = 4.dp)
    ) {
        if (daily.isEmpty()) return@Canvas
        val maxScore = 100.0
        val minScore = 0.0
        val stepX = size.width / (daily.size - 1).coerceAtLeast(1)
        val points = daily.mapIndexed { index, score ->
            Offset(
                x = stepX * index,
                y =
                size.height -
                    ((score.avgTotal - minScore) / (maxScore - minScore) * size.height).toFloat()
            )
        }
        // Grid lines
        for (i in 1..3) {
            val y = size.height * i / 4f
            drawLine(
                color = grid,
                start = Offset(0f, y),
                end = Offset(size.width, y),
                strokeWidth = 1f,
                pathEffect = PathEffect.dashPathEffect(floatArrayOf(8f, 8f))
            )
        }
        // Smooth path through points
        val path = Path().apply {
            moveTo(points.first().x, points.first().y)
            for (i in 1 until points.size) {
                val prev = points[i - 1]
                val cur = points[i]
                val midX = (prev.x + cur.x) / 2f
                cubicTo(
                    midX,
                    prev.y,
                    midX,
                    cur.y,
                    cur.x,
                    cur.y
                )
            }
        }
        drawPath(path = path, color = color, style = Stroke(width = 4f))
        // Points
        points.forEach { p ->
            drawCircle(color = color, radius = 5f, center = p)
        }
    }
}

@Composable
private fun SubjectBreakdownCard(stats: PracticeStats) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Text(
                text = "分项平均",
                style = MaterialTheme.typography.titleMedium
            )
            SubjectBar("发音", stats.avgPronunciation)
            SubjectBar("流利度", stats.avgFluency)
            SubjectBar("完整度", stats.avgCompleteness)
        }
    }
}

@Composable
private fun SubjectBar(label: String, value: Double) {
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween
        ) {
            Text(label, style = MaterialTheme.typography.bodyMedium)
            Text(
                text = value.toInt().toString(),
                style = MaterialTheme.typography.bodyMedium,
                color = ScoreColorMapper.level(value).color(),
                fontWeight = FontWeight.Bold
            )
        }
        ScoreProgress(value = value)
    }
}

@Composable
private fun ScoreProgress(value: Double) {
    val color = ScoreColorMapper.level(value).color()
    Surface(
        shape = RoundedCornerShape(6.dp),
        color = MaterialTheme.colorScheme.surfaceVariant,
        modifier = Modifier.fillMaxWidth().height(8.dp)
    ) {
        Box(modifier = Modifier.fillMaxSize()) {
            Surface(
                shape = RoundedCornerShape(6.dp),
                color = color,
                modifier = Modifier
                    .fillMaxWidth(fraction = (value / 100.0).toFloat().coerceIn(0f, 1f))
                    .fillMaxSize()
            ) {}
        }
    }
}

@Composable
private fun EmptyDashboard() {
    Column(
        modifier = Modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Icon(
            imageVector = Icons.Filled.LocalFireDepartment,
            contentDescription = null,
            tint = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(56.dp)
        )
        Text(
            text = "还没有练习记录",
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(top = 16.dp)
        )
        Text(
            text = "完成第一次跟读或自由对话后，这里会显示你的总练习次数、平均分、连续天数等数据。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp)
        )
    }
}
