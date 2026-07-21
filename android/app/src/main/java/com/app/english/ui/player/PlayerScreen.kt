package com.app.english.ui.player

import android.Manifest
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
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.RecordingLevelIndicator
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

/**
 * Top-level entry point for the read-along / dialogue / free-dialogue
 * practice flow. Holds the Scaffold + permissions, then delegates the
 * mode-specific content to [PlayerContent]. Sub-composables live in
 * [PlayerControls], [PlayerReadAlongView], [PlayerDialogueView], and
 * [PlayerScorePanel].
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalPermissionsApi::class)
@Composable
fun PlayerScreen(
    onBack: () -> Unit,
    onFinish: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: PlayerViewModel = hiltViewModel()
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
                        Text(text = state.lessonTitle, style = MaterialTheme.typography.titleMedium)
                        Text(
                            text = when (state.mode) {
                                PlayerMode.READ_ALONG ->
                                    "跟读模式 · 第 ${state.currentIndex + 1}/${state.lines.size} 句"
                                PlayerMode.DIALOGUE ->
                                    "对话模式 · 角色 ${state.roleName} · 第 " +
                                        "${state.currentIndex + 1}/${state.lines.size} 句"
                                PlayerMode.FREE_DIALOGUE -> "自由对话模式"
                            },
                            style = MaterialTheme.typography.labelLarge
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
        bottomBar = {
            if (state.mode != PlayerMode.FREE_DIALOGUE && state.lines.isNotEmpty()) {
                val progress =
                    (state.currentIndex + 1).toFloat() / state.lines.size.coerceAtLeast(1)
                LinearProgressIndicator(
                    progress = { progress.coerceIn(0f, 1f) },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        when {
            state.isLoading -> LoadingState(Modifier.padding(padding))
            state.error != null && state.lines.isEmpty() -> ErrorState(
                message = state.error ?: "加载失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::reload
            )
            else -> PlayerContent(
                state = state,
                micGranted = micPermission.status.isGranted,
                onRequestPermission = { micPermission.launchPermissionRequest() },
                onPlayReference = viewModel::playReference,
                onStartRecording = viewModel::startRecording,
                onStopAndSubmit = viewModel::stopAndSubmit,
                onNext = viewModel::nextLine,
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun PlayerContent(
    state: PlayerUiState,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onPlayReference: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndSubmit: () -> Unit,
    onNext: () -> Unit,
    modifier: Modifier = Modifier
) {
    val line = state.currentLine
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        if (line == null) {
            Text("没有可朗读的句子", style = MaterialTheme.typography.bodyLarge)
            return@Column
        }

        when (state.mode) {
            PlayerMode.READ_ALONG -> {
                RecentSentenceList(
                    lines = state.recentLines,
                    currentLineId = line.id,
                    completedCount = state.currentIndex
                )
                LineHeader(
                    title = "请跟读当前句",
                    text = line.text,
                    ipa = line.ipa,
                    translation = line.translation
                )
                ReferenceButton(
                    isPlaying = state.isPlayingReference,
                    label = "播放标准音",
                    onClick = onPlayReference
                )
            }
            PlayerMode.DIALOGUE -> {
                DialogueTranscript(
                    conversation = state.conversation,
                    currentLineId = line.id
                )
                state.currentPrompt?.let { prompt ->
                    PromptCard(
                        role = "角色 A",
                        text = prompt.text,
                        isPlaying = state.isPlayingReference,
                        onPlay = onPlayReference
                    )
                }
                LineHeader(
                    title = "轮到角色 ${state.roleName}，请朗读",
                    text = line.text,
                    ipa = line.ipa,
                    translation = line.translation
                )
            }
            PlayerMode.FREE_DIALOGUE -> Unit
        }

        if (!micGranted) PermissionHint(onRequestPermission = onRequestPermission)

        RecordingLevelIndicator(
            level = state.micLevel,
            active = state.isRecording,
            modifier = Modifier.fillMaxWidth()
        )
        RecordButton(
            isRecording = state.isRecording,
            isSubmitting = state.isSubmitting,
            hasScore = state.currentScore != null,
            micGranted = micGranted,
            onRequestPermission = onRequestPermission,
            onStartRecording = onStartRecording,
            onStopAndSubmit = onStopAndSubmit
        )

        if (state.isSubmitting) {
            Row {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("评分中...", style = MaterialTheme.typography.bodyMedium)
            }
        }

        state.currentScore?.let { score ->
            ScorePanel(score = score, needsRerecord = !state.canAdvance)
            AdvanceButton(
                canAdvance = state.canAdvance,
                isLastLine = state.isLastLine,
                onNext = onNext
            )
        }
    }
}
