package com.app.english.ui.scenes

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SuggestionChip
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.domain.model.VocabCard
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.theme.Spacings

/**
 * 课程详情页(计划 §6.4): 顶部标题区 + 核心词汇横滑卡(点击播放) + 三段进度
 * (打基础→实战→复盘) + 任务清单预览 + 「开始学习/继续学习」大按钮。
 */
@Composable
fun SceneDetailScreen(
    onBack: () -> Unit,
    onOpenBriefing: (sessionId: String) -> Unit,
    onOpenMission: (sessionId: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: SceneDetailViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val course = state.course
    Column(modifier = modifier.fillMaxSize()) {
        SceneDetailTopBar(onBack = onBack)
        when {
            state.isLoading -> LoadingState()
            state.error != null && course == null -> ErrorState(
                message = state.error ?: "加载课程失败",
                onRetry = viewModel::load
            )
            course != null -> Column(
                modifier = Modifier
                    .fillMaxSize()
                    .verticalScroll(rememberScrollState())
                    .padding(horizontal = Spacings.s3)
                    .padding(bottom = Spacings.s4),
                verticalArrangement = Arrangement.spacedBy(Spacings.s3)
            ) {
                SceneHeader(course)
                VocabSection(
                    course = course,
                    playingText = state.playingText,
                    onPlay = viewModel::playSpeech
                )
                StageProgress(resuming = state.resuming)
                TaskPreview(course)
                state.error?.let { message ->
                    Text(
                        text = message,
                        color = MaterialTheme.colorScheme.error,
                        style = MaterialTheme.typography.bodySmall
                    )
                }
                StartButton(
                    state = state,
                    onClick = {
                        viewModel.startLearning(
                            onOpenBriefing = onOpenBriefing,
                            onOpenMission = onOpenMission
                        )
                    }
                )
                Spacer(Modifier.height(Spacings.s2))
            }
        }
    }
}

@Composable
private fun SceneDetailTopBar(onBack: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacings.s2, vertical = Spacings.s2),
        verticalAlignment = Alignment.CenterVertically
    ) {
        androidx.compose.material3.TextButton(onClick = onBack) { Text("← 返回") }
    }
}

@Composable
private fun SceneHeader(course: SceneCourseDetail) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
        Text(course.title, style = MaterialTheme.typography.headlineSmall)
        if (course.subtitleEn.isNotBlank()) {
            Text(
                text = course.subtitleEn,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
        Row(horizontalArrangement = Arrangement.spacedBy(Spacings.s1)) {
            SuggestionChip(
                onClick = {},
                label = { Text(course.level) },
                enabled = false
            )
            SuggestionChip(
                onClick = {},
                label = { Text("约 ${course.estMinutes} 分钟") },
                enabled = false
            )
            if (course.isGenerated) {
                SuggestionChip(
                    onClick = {},
                    label = { Text("AI 生成") },
                    enabled = false
                )
            }
        }
        if (course.briefCn.isNotBlank()) {
            Text(
                text = course.briefCn,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun VocabSection(
    course: SceneCourseDetail,
    playingText: String?,
    onPlay: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        Text("核心词汇", style = MaterialTheme.typography.titleMedium)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacings.s2)) {
            items(course.vocab, key = { it.word }) { card ->
                VocabCardItem(card = card, isPlaying = playingText == card.word, onPlay = onPlay)
            }
        }
    }
}

@Composable
private fun VocabCardItem(card: VocabCard, isPlaying: Boolean, onPlay: (String) -> Unit) {
    Card(
        onClick = { onPlay(card.word) },
        modifier = Modifier.width(200.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (isPlaying) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface
            }
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text(card.word, style = MaterialTheme.typography.titleLarge)
            if (card.ipa.isNotBlank()) {
                Text(
                    text = card.ipa,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text(card.meaningCn, style = MaterialTheme.typography.bodyMedium)
            Text(
                text = card.exampleEn,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 2,
                overflow = TextOverflow.Ellipsis
            )
        }
    }
}

/** 三段进度: 打基础→实战→复盘, 按最近会话 stage 点亮。 */
@Composable
private fun StageProgress(resuming: com.app.english.domain.model.ContinueSession?) {
    val stage = resuming?.stage ?: ""
    val labels = listOf("打基础", "实战对话", "复盘")
    val activeIndex = when {
        stage == "mission" -> 1
        stage == "review" || stage == "done" -> 2
        else -> 0
    }
    Card(colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)) {
        Column(
            modifier = Modifier.padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
            ) {
                labels.forEachIndexed { index, label ->
                    val reached = index <= activeIndex
                    Box(
                        modifier = Modifier
                            .weight(1f)
                            .height(6.dp)
                            .background(
                                color = if (reached) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.surfaceVariant
                                },
                                shape = RoundedCornerShape(3.dp)
                            )
                    )
                }
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
            ) {
                labels.forEachIndexed { index, label ->
                    Text(
                        text = if (resuming != null &&
                            index == activeIndex
                        ) {
                            "$label (进行中)"
                        } else {
                            label
                        },
                        style = MaterialTheme.typography.labelSmall,
                        color = if (index <= activeIndex && resuming != null) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            Color.Unspecified
                        },
                        modifier = Modifier.weight(1f)
                    )
                }
            }
            resuming?.let { resume ->
                Text(
                    text = "上次练到 ${resume.title} · 打基础 ${resume.doneSteps}/${resume.totalSteps}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun TaskPreview(course: SceneCourseDetail) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        Text("实战任务", style = MaterialTheme.typography.titleMedium)
        Text(
            text = "和「${course.mission.personaCn}」对话, 达成 ${course.requiredTaskCount} 个必做任务",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        course.mission.tasks.forEach { task ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    imageVector = Icons.Filled.CheckCircle,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.surfaceVariant
                )
                Spacer(Modifier.width(Spacings.s1))
                Text(
                    text = task.descCn + if (task.required) "" else "(选做)",
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}

@Composable
private fun StartButton(state: SceneDetailUiState, onClick: () -> Unit) {
    Button(
        onClick = onClick,
        enabled = !state.isStarting,
        modifier = Modifier
            .fillMaxWidth()
            .height(52.dp)
    ) {
        if (state.isStarting) {
            CircularProgressIndicator(
                modifier = Modifier.height(20.dp),
                strokeWidth = 2.dp,
                color = MaterialTheme.colorScheme.onPrimary
            )
        } else if (state.resuming != null) {
            Text("继续学习")
        } else {
            Text("开始学习")
        }
    }
}
