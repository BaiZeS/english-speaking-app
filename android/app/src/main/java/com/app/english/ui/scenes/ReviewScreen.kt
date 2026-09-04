package com.app.english.ui.scenes

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
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
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ReviewReportData
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.theme.Spacings

/**
 * 复盘报告页(计划 §6.4): 总分圆环 + 4 维分条(无证据维度诚实显示「本轮无证据」)
 * + ability_delta 角标 + 任务清单 + 原话 vs 更好说法对照 + new_tokens + 参考剧本。
 */
@Composable
fun ReviewScreen(
    onBack: () -> Unit,
    onReplay: (sceneId: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ReviewViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val report = state.report
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacings.s3),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = onBack) { Text("← 完成") }
            report?.let {
                TextButton(onClick = { onReplay(it.sceneId) }) { Text("再来一课") }
            }
        }
        when {
            state.isLoading -> LoadingState()
            report == null -> ErrorState(
                message = state.error ?: "加载复盘失败",
                onRetry = viewModel::load
            )
            else -> {
                OverallRing(report)
                if (report.source != "llm") {
                    DegradedBanner("本场文案由离线规则生成 (source=${report.source}), 配好 LLM 后会更细")
                }
                DimBars(report)
                ChecklistCard(report)
                PairsCard(report)
                HighlightsCard(report)
                if (report.newTokens.isNotEmpty()) TokensCard(report)
                state.course?.let { course ->
                    ScriptCard(course.id, course, state.isPlayingLine, viewModel::playLine)
                }
            }
        }
    }
}

@Composable
private fun OverallRing(report: ReviewReportData) {
    val overall = report.overall
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s3),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Text(report.title, style = MaterialTheme.typography.titleMedium)
            Box(contentAlignment = Alignment.Center, modifier = Modifier.size(140.dp)) {
                val track = MaterialTheme.colorScheme.surfaceVariant
                val progress = MaterialTheme.colorScheme.primary
                Canvas(Modifier.size(140.dp)) {
                    drawArc(
                        color = track,
                        startAngle = -90f,
                        sweepAngle = 360f,
                        useCenter = false,
                        style = Stroke(width = 14.dp.toPx(), cap = StrokeCap.Round)
                    )
                    if (overall != null) {
                        drawArc(
                            color = progress,
                            startAngle = -90f,
                            sweepAngle = (360f * overall / 100f).toFloat(),
                            useCenter = false,
                            style = Stroke(width = 14.dp.toPx(), cap = StrokeCap.Round)
                        )
                    }
                }
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(
                        text = overall?.let { "${it.toInt()}" } ?: "—",
                        style = MaterialTheme.typography.displaySmall
                    )
                    Text(
                        text = if (report.cleared) "通关成功" else "未通关",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            Text(
                text = "实战 ${report.turnCount}/${report.maxTurns} 轮 · 提示 ${report.hintsUsed} 次" +
                    if (report.autoFinished) " · 到顶自动收工" else "",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun DimBars(report: ReviewReportData) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Text("四维表现", style = MaterialTheme.typography.titleSmall)
            report.dimOrder.forEach { dim ->
                val value = report.dims[dim]
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        text = dimLabel(dim),
                        style = MaterialTheme.typography.labelMedium,
                        modifier = Modifier.size(width = 64.dp, height = 20.dp)
                    )
                    if (value == null) {
                        Text(
                            text = "本轮无证据",
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    } else {
                        Box(
                            modifier = Modifier
                                .weight(1f)
                                .height(8.dp)
                                .background(
                                    MaterialTheme.colorScheme.surfaceVariant,
                                    RoundedCornerShape(4.dp)
                                )
                        ) {
                            Box(
                                modifier = Modifier
                                    .fillMaxWidth(value.toFloat() / 100f)
                                    .height(8.dp)
                                    .background(
                                        MaterialTheme.colorScheme.primary,
                                        RoundedCornerShape(4.dp)
                                    )
                            )
                        }
                        Text(
                            text = " ${value.toInt()}",
                            style = MaterialTheme.typography.labelMedium
                        )
                    }
                    report.abilityDelta[dim]?.let { delta ->
                        Text(
                            text = (if (delta >= 0) "+" else "") + "%.1f".format(delta),
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.tertiary
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun ChecklistCard(report: ReviewReportData) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text("任务清单", style = MaterialTheme.typography.titleSmall)
            report.checklist.forEach { task ->
                Row {
                    Text(
                        text = if (task.done) "✓" else "○",
                        color = if (task.done) {
                            MaterialTheme.colorScheme.tertiary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        }
                    )
                    Box(Modifier.size(Spacings.tiny))
                    Column {
                        Text(
                            text = task.descCn + if (task.required) "" else " (选做)",
                            style = MaterialTheme.typography.bodyMedium
                        )
                        if (task.done && task.evidence.isNotBlank()) {
                            Text(
                                text = task.evidence,
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                }
            }
        }
    }
}

/** 原话 vs 更好说法对照(绿卡=润色句, 删除线=原句)。 */
@Composable
private fun PairsCard(report: ReviewReportData) {
    if (report.transcriptPairs.isEmpty()) return
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Text("原话 vs 更好说法", style = MaterialTheme.typography.titleSmall)
            report.transcriptPairs.forEach { pair ->
                Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                    Text(
                        text = pair.original,
                        style = MaterialTheme.typography.bodySmall,
                        textDecoration = TextDecoration.LineThrough,
                        color = MaterialTheme.colorScheme.error
                    )
                    Text(
                        text = pair.polished,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.tertiary
                    )
                    if (pair.explanationCn.isNotBlank()) {
                        Text(
                            text = pair.explanationCn,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun HighlightsCard(report: ReviewReportData) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text("亮点与建议", style = MaterialTheme.typography.titleSmall)
            report.highlights.forEach { line ->
                Text(
                    text = "✦ $line",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            }
            report.improvements.forEach { line ->
                Text(
                    text = "▲ $line",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun TokensCard(report: ReviewReportData) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text("本次用上的课内词", style = MaterialTheme.typography.titleSmall)
            Text(
                text = report.newTokens.joinToString("  ") { "✓ $it" },
                style = MaterialTheme.typography.bodyMedium
            )
        }
    }
}

@Composable
private fun ScriptCard(
    sceneId: String,
    course: com.app.english.domain.model.SceneCourseDetail,
    isPlaying: Boolean,
    onPlayLine: (String) -> Unit
) {
    Card {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text("参考剧本", style = MaterialTheme.typography.titleSmall)
            course.mission.exchanges.forEach { exchange ->
                TextButton(onClick = { onPlayLine(exchange.a) }, enabled = !isPlaying) {
                    Text("A: ${exchange.a}", color = Color.Gray)
                }
                TextButton(onClick = { onPlayLine(exchange.b) }, enabled = !isPlaying) {
                    Text("你: ${exchange.b}", color = MaterialTheme.colorScheme.primary)
                }
            }
        }
    }
}

@Composable
private fun DegradedBanner(message: String) {
    Card(
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Text(
            text = message,
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2)
        )
    }
}

private fun dimLabel(dim: String): String = when (dim) {
    "pronunciation" -> "发音"
    "grammar" -> "语法"
    "vocabulary" -> "词汇"
    "fluency" -> "流利度"
    else -> dim
}
