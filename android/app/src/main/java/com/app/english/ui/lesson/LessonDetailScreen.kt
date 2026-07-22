package com.app.english.ui.lesson

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
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
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.LessonProgress
import com.app.english.domain.model.Line
import com.app.english.domain.model.Role
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.player.PlayerMode
import com.app.english.ui.theme.color

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonDetailScreen(
    onBack: () -> Unit,
    onStartPractice: (lessonId: Int, mode: PlayerMode) -> Unit,
    onStartFreeDialogue: (lessonId: Int) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: LessonDetailViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("课程详情") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        when (val current = state) {
            is LessonDetailUiState.Loading -> LoadingState(Modifier.padding(padding))
            is LessonDetailUiState.Error -> ErrorState(
                message = current.message,
                modifier = Modifier.padding(padding),
                onRetry = viewModel::load
            )
            is LessonDetailUiState.Success -> LessonDetailBody(
                lesson = current.lesson,
                onStart = { mode -> onStartPractice(viewModel.lessonId, mode) },
                onStartFreeDialogue = { onStartFreeDialogue(viewModel.lessonId) },
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun LessonDetailBody(
    lesson: LessonDetail,
    onStart: (PlayerMode) -> Unit,
    onStartFreeDialogue: () -> Unit,
    modifier: Modifier = Modifier
) {
    val totalLines = lesson.roles.sumOf { it.lines.size }
    val totalRoles = lesson.roles.size
    val totalWords = lesson.roles.sumOf { role ->
        role.lines.sumOf { line -> countWords(line.text) }
    }
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item { LessonHeader(lesson = lesson) }
        item {
            LessonStatsRow(
                totalLines = totalLines,
                totalRoles = totalRoles,
                totalWords = totalWords
            )
        }
        state.progress?.takeIf { it.isPracticed }?.let { progress ->
            item { ProgressCard(progress = progress) }
        }
        item { PreviewSection(lesson = lesson) }
        item {
            Text(
                text = "选择练习方式",
                style = MaterialTheme.typography.titleMedium,
                modifier = Modifier.padding(top = 8.dp)
            )
        }
        item {
            ModeCard(
                icon = Icons.Filled.MenuBook,
                title = "跟读模式",
                description = "按句子练习，最近五句会显示在屏幕上，不区分角色。",
                meta = "$totalLines 句 · 标准音 + 发音评分",
                onClick = { onStart(PlayerMode.READ_ALONG) },
                highlighted = true
            )
        }
        item {
            ModeCard(
                icon = Icons.Filled.ChatBubbleOutline,
                title = "对话模式",
                description = "完整展示角色 A/B 对话。点击播放 A，轮到 B 时由你朗读并评分。",
                meta = "角色 A 示范 · 角色 B 跟读",
                onClick = { onStart(PlayerMode.DIALOGUE) }
            )
        }
        item {
            ModeCard(
                icon = Icons.Filled.AutoAwesome,
                title = "自由对话模式",
                description = "和 AI 自由交流，每轮提供建议回答，你可以自由发挥并获得评分。",
                meta = "AI 场景 · 每轮评分",
                onClick = onStartFreeDialogue
            )
        }
    }
}

@Composable
private fun LessonHeader(lesson: LessonDetail) {
    Column {
        Text(
            text = "Lesson ${lesson.lessonNo}",
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(text = lesson.title, style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "先看看本课内容，再选择练习方式",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 4.dp)
        )
    }
}

@Composable
private fun LessonStatsRow(totalLines: Int, totalRoles: Int, totalWords: Int) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(8.dp)
    ) {
        StatPill(value = "$totalLines", label = "句", modifier = Modifier.weight(1f))
        StatPill(value = "$totalRoles", label = "角色", modifier = Modifier.weight(1f))
        StatPill(value = "$totalWords", label = "词", modifier = Modifier.weight(1f))
    }
}

@Composable
private fun StatPill(value: String, label: String, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(12.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = value,
                style = MaterialTheme.typography.titleLarge,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
        }
    }
}

@Composable
private fun PreviewSection(lesson: LessonDetail) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text(
                text = "课文预览",
                style = MaterialTheme.typography.titleMedium
            )
            Text(
                text = "前几行 + 角色分布",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            // Show up to 3 lines from the first non-empty role.
            val firstRole = lesson.roles.firstOrNull { it.lines.isNotEmpty() }
            val sampleLines = firstRole?.lines?.take(3).orEmpty()
            sampleLines.forEachIndexed { index, line ->
                PreviewLine(index = index, line = line)
                if (index < sampleLines.lastIndex) {
                    HorizontalDivider(
                        color = MaterialTheme.colorScheme.surfaceVariant,
                        modifier = Modifier.padding(vertical = 4.dp)
                    )
                }
            }
            if ((firstRole?.lines?.size ?: 0) > sampleLines.size) {
                Text(
                    text = "…还有 ${(firstRole?.lines?.size ?: 0) - sampleLines.size} 行",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (lesson.roles.size > 1) {
                Spacer(Modifier.height(4.dp))
                RoleDistribution(roles = lesson.roles)
            }
        }
    }
}

@Composable
private fun PreviewLine(index: Int, line: Line) {
    Row(verticalAlignment = Alignment.Top) {
        Surface(
            shape = CircleShape,
            color = MaterialTheme.colorScheme.primary,
            modifier = Modifier.size(22.dp)
        ) {
            Box(contentAlignment = Alignment.Center) {
                Text(
                    text = "${index + 1}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onPrimary
                )
            }
        }
        Spacer(Modifier.width(10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(text = line.text, style = MaterialTheme.typography.bodyLarge)
            line.ipa?.takeIf { it.isNotBlank() }?.let { ipa ->
                Text(
                    text = "/$ipa/",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 2.dp)
                )
            }
            line.translation?.takeIf { it.isNotBlank() }?.let { translation ->
                Text(
                    text = translation,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 2.dp)
                )
            }
        }
    }
}

@Composable
private fun RoleDistribution(roles: List<Role>) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(
            text = "角色台词",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        roles.forEach { role ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = role.name,
                    style = MaterialTheme.typography.labelLarge,
                    modifier = Modifier.width(40.dp)
                )
                Surface(
                    shape = RoundedCornerShape(3.dp),
                    color = MaterialTheme.colorScheme.primary.copy(alpha = 0.4f),
                    modifier = Modifier
                        .weight(1f)
                        .height(6.dp)
                ) {
                    // Bar width encodes relative line count for the role.
                    val maxLines = roles.maxOf { it.lines.size }.coerceAtLeast(1)
                    val weight = role.lines.size.toFloat() / maxLines
                    Box(
                        modifier = Modifier
                            .fillMaxWidth(fraction = weight)
                            .height(6.dp)
                            .clip(RoundedCornerShape(3.dp))
                            .padding(0.dp)
                    ) {
                        Surface(
                            color = MaterialTheme.colorScheme.primary,
                            modifier = Modifier.fillMaxSize()
                        ) {}
                    }
                }
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "${role.lines.size}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun ModeCard(
    icon: androidx.compose.ui.graphics.vector.ImageVector,
    title: String,
    description: String,
    meta: String,
    onClick: () -> Unit,
    highlighted: Boolean = false
) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        shape = RoundedCornerShape(14.dp),
        colors = CardDefaults.cardColors(
            containerColor = if (highlighted) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surface
            }
        )
    ) {
        Row(modifier = Modifier.padding(18.dp), verticalAlignment = Alignment.Top) {
            Icon(
                imageVector = icon,
                contentDescription = null,
                tint = if (highlighted) {
                    MaterialTheme.colorScheme.onPrimaryContainer
                } else {
                    MaterialTheme.colorScheme.primary
                },
                modifier = Modifier.padding(top = 2.dp)
            )
            Spacer(Modifier.width(12.dp))
            Column {
                Text(text = title, style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(6.dp))
                Text(text = description, style = MaterialTheme.typography.bodyMedium)
                Spacer(Modifier.height(8.dp))
                Text(
                    text = meta,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

private fun countWords(text: String): Int = text.split(Regex("\\s+")).count { it.isNotBlank() }

@Composable
private fun ProgressCard(progress: LessonProgress) {
    val color = ScoreColorMapper.level(progress.bestScore).color()
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer
        )
    ) {
        Row(
            modifier = Modifier.padding(16.dp).fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(12.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column(
                modifier = Modifier.width(96.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = progress.bestScore.toInt().toString(),
                    style = MaterialTheme.typography.headlineMedium,
                    color = color,
                    fontWeight = FontWeight.Bold
                )
                Text(
                    text = "最高分",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
            }
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    text = "本课战绩",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
                Text(
                    text =
                    "已练习 " + progress.attemptCount + " 次 · 上次 " + progress.lastScore.toInt() +
                        " 分",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
                progress.lastPracticedAt?.let { ts ->
                    Text(
                        text = "最近：" + formatRelativeTime(ts),
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onTertiaryContainer
                    )
                }
            }
        }
    }
}

private fun formatRelativeTime(iso: String): String = iso.take(10)
