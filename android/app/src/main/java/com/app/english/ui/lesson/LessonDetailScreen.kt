package com.app.english.ui.lesson

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.LessonDetail
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.player.PlayerMode

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
                title = { Text("练习模式") },
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
            is LessonDetailUiState.Success -> ModeList(
                lesson = current.lesson,
                onStart = { mode -> onStartPractice(viewModel.lessonId, mode) },
                onStartFreeDialogue = { onStartFreeDialogue(viewModel.lessonId) },
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun ModeList(
    lesson: LessonDetail,
    onStart: (PlayerMode) -> Unit,
    onStartFreeDialogue: () -> Unit,
    modifier: Modifier = Modifier
) {
    val totalLines = lesson.roles.sumOf { it.lines.size }
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        item {
            Column {
                Text(
                    text = "Lesson ${lesson.lessonNo}",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(text = lesson.title, style = MaterialTheme.typography.headlineSmall)
                Text(
                    text = "选择一种方式开始练习",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
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
