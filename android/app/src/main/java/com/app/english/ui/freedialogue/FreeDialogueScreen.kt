package com.app.english.ui.freedialogue

import android.Manifest
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.theme.color
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

@OptIn(ExperimentalMaterial3Api::class, ExperimentalPermissionsApi::class)
@Composable
fun FreeDialogueScreen(
    onBack: () -> Unit,
    onFinish: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: FreeDialogueViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)

    LaunchedEffect(state.finished) {
        if (state.finished) onFinish()
    }
    LaunchedEffect(state.error) {
        state.error?.let { message ->
            snackbarHostState.showSnackbar(message)
            viewModel.dismissError()
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text(state.title, style = MaterialTheme.typography.titleMedium)
                        Text(
                            "自由对话 · 已完成 ${state.scores.size} 轮",
                            style = MaterialTheme.typography.labelLarge
                        )
                    }
                },
                actions = {
                    if (state.scenes.size > 1) {
                        ScenePicker(
                            scenes = state.scenes,
                            selectedId = state.selectedSceneId,
                            onSelect = viewModel::selectScene
                        )
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        when {
            state.isLoading -> LoadingState(Modifier.padding(padding))
            state.error != null && state.messages.isEmpty() -> ErrorState(
                message = state.error ?: "加载失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::generate
            )
            else -> FreeDialogueContent(
                state = state,
                micGranted = micPermission.status.isGranted,
                onRequestPermission = { micPermission.launchPermissionRequest() },
                onPlayAssistant = viewModel::playLatestAssistant,
                onStartRecording = viewModel::startRecording,
                onStopAndSubmit = viewModel::stopAndSubmit,
                onFinish = viewModel::finish,
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun FreeDialogueContent(
    state: FreeDialogueUiState,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onPlayAssistant: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndSubmit: () -> Unit,
    onFinish: () -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text(
            "和 AI 自由交流。参考回答只用于评分，你可以用自己的方式表达。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )

        state.messages.forEach { message ->
            MessageBubble(message)
        }

        state.messages.lastOrNull { !it.isUser }?.let { assistant ->
            OutlinedButton(
                onClick = onPlayAssistant,
                enabled = !state.isPlayingReference && !state.isRecording,
                modifier = Modifier.fillMaxWidth()
            ) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(if (state.isPlayingReference) "AI 播放中..." else "播放 AI 的话")
            }
        }

        Card(
            modifier = Modifier.fillMaxWidth(),
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
        ) {
            Column(Modifier.padding(16.dp)) {
                Text(
                    "参考回答（可自由发挥）",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Text(
                    state.suggestedReply,
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }

        if (!micGranted) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(16.dp)) {
                    Text("需要录音权限才能进行自由对话。")
                    Button(onClick = onRequestPermission, modifier = Modifier.padding(top = 8.dp)) {
                        Text("授予权限")
                    }
                }
            }
        }

        when {
            state.isSubmitting -> {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(modifier = Modifier.size(20.dp))
                    Spacer(Modifier.width(8.dp))
                    Text("评分并生成下一轮对话...")
                }
            }
            state.isRecording -> {
                Button(
                    onClick = onStopAndSubmit,
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = MaterialTheme.colorScheme.error
                    )
                ) {
                    Icon(Icons.Filled.Stop, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text("停止回答并评分")
                }
            }
            else -> {
                Button(
                    onClick = { if (micGranted) onStartRecording() else onRequestPermission() },
                    modifier = Modifier.fillMaxWidth()
                ) {
                    Icon(Icons.Filled.Mic, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(if (state.currentScore == null) "开始回答" else "回答下一轮")
                }
            }
        }

        state.currentScore?.let { FreeScoreCard(it) }

        OutlinedButton(
            onClick = onFinish,
            enabled = state.scores.isNotEmpty() && !state.isRecording && !state.isSubmitting,
            modifier = Modifier.fillMaxWidth()
        ) {
            Text("结束练习并查看总分")
        }
    }
}

@Composable
private fun MessageBubble(message: FreeDialogueMessage) {
    val container = if (message.isUser) {
        MaterialTheme.colorScheme.secondaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = if (message.isUser) Arrangement.End else Arrangement.Start
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth(0.88f)
                .background(container, RoundedCornerShape(14.dp))
                .padding(14.dp)
        ) {
            Text(
                if (message.isUser) "我" else "AI",
                style = MaterialTheme.typography.labelMedium,
                fontWeight = FontWeight.Bold,
                color = MaterialTheme.colorScheme.primary
            )
            Text(
                message.text,
                style = MaterialTheme.typography.bodyLarge,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
    }
}

@Composable
private fun FreeScoreCard(score: ScoreResult) {
    val color = ScoreColorMapper.level(score.total).color()
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Text("本轮得分", style = MaterialTheme.typography.titleMedium)
            Text(
                text = score.total.toInt().toString(),
                style = MaterialTheme.typography.headlineMedium,
                color = color,
                fontWeight = FontWeight.Bold
            )
            Text(
                "发音 ${score.pronunciation.toInt()} · " +
                    "流利度 ${score.fluency.toInt()} · 完整度 ${score.completeness.toInt()}",
                style = MaterialTheme.typography.bodyMedium
            )
            score.suggestion?.takeIf { it.isNotBlank() }?.let {
                Text("建议：$it", color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
        }
    }
}

@Composable
private fun ScenePicker(
    scenes: List<com.app.english.domain.model.DialogueScene>,
    selectedId: String,
    onSelect: (String) -> Unit
) {
    var expanded by androidx.compose.runtime.remember {
        androidx.compose.runtime.mutableStateOf(false)
    }
    val selected = scenes.firstOrNull { it.id == selectedId } ?: scenes.firstOrNull()
    Box {
        TextButton(onClick = { expanded = true }) {
            Text(
                text = selected?.title ?: "切换场景",
                style = MaterialTheme.typography.labelLarge
            )
            Icon(
                Icons.Filled.ArrowDropDown,
                contentDescription = null,
                modifier = Modifier.size(18.dp)
            )
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { expanded = false }) {
            scenes.forEach { scene ->
                DropdownMenuItem(
                    text = {
                        Column {
                            Text(scene.title, style = MaterialTheme.typography.bodyLarge)
                            if (scene.description.isNotBlank()) {
                                Text(
                                    text = scene.description,
                                    style = MaterialTheme.typography.bodySmall,
                                    color = MaterialTheme.colorScheme.onSurfaceVariant
                                )
                            }
                        }
                    },
                    onClick = {
                        onSelect(scene.id)
                        expanded = false
                    }
                )
            }
        }
    }
}
