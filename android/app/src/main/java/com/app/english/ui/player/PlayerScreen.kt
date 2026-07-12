package com.app.english.ui.player

import android.Manifest
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
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
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
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
        state.error?.let { msg ->
            snackbarHostState.showSnackbar(msg)
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
                        val progress = "角色 ${state.roleName} · " +
                            "第 ${state.currentIndex + 1}/${state.lines.size} 句"
                        Text(
                            text = progress,
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
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        if (line == null) {
            Text("没有可朗读的台词", style = MaterialTheme.typography.bodyLarge)
            return@Column
        }

        LineHeader(line.text, line.ipa, line.translation)
        if (!micGranted) {
            PermissionHint(onRequestPermission = onRequestPermission)
        }

        ReferenceButton(isPlaying = state.isPlayingReference, onClick = onPlayReference)

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
            Row(verticalAlignment = Alignment.CenterVertically) {
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

@Composable
private fun LineHeader(text: String, ipa: String?, translation: String?) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(Modifier.padding(16.dp)) {
            Text(text = text, style = MaterialTheme.typography.headlineMedium)
            ipa?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = "/$it/",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
            translation?.takeIf { it.isNotBlank() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(top = 8.dp)
                )
            }
        }
    }
}

@Composable
private fun PermissionHint(onRequestPermission: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(
                text = "需要录音权限才能进行跟读练习。",
                style = MaterialTheme.typography.bodyMedium
            )
            Button(onClick = onRequestPermission, modifier = Modifier.padding(top = 8.dp)) {
                Text("授予权限")
            }
        }
    }
}

@Composable
private fun ReferenceButton(isPlaying: Boolean, onClick: () -> Unit) {
    OutlinedButton(
        onClick = onClick,
        modifier = Modifier.fillMaxWidth(),
        enabled = !isPlaying
    ) {
        Icon(Icons.Filled.PlayArrow, contentDescription = null)
        Spacer(Modifier.width(8.dp))
        Text(if (isPlaying) "播放中..." else "播放标准音")
    }
}

@Composable
private fun RecordButton(
    isRecording: Boolean,
    isSubmitting: Boolean,
    hasScore: Boolean,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndSubmit: () -> Unit
) {
    when {
        isSubmitting -> Button(
            onClick = {},
            modifier = Modifier.fillMaxWidth(),
            enabled = false
        ) {
            Text("评分中...")
        }

        isRecording -> Button(
            onClick = onStopAndSubmit,
            modifier = Modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
        ) {
            Icon(Icons.Filled.Stop, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("停止录音并评分")
        }

        else -> Button(
            onClick = { if (micGranted) onStartRecording() else onRequestPermission() },
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(Icons.Filled.Mic, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(if (hasScore) "重录" else "开始录音")
        }
    }
}

@Composable
private fun AdvanceButton(canAdvance: Boolean, isLastLine: Boolean, onNext: () -> Unit) {
    Button(
        onClick = onNext,
        modifier = Modifier.fillMaxWidth(),
        enabled = canAdvance
    ) {
        Text(if (isLastLine) "完成" else "下一句")
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun ScorePanel(score: ScoreResult, needsRerecord: Boolean) {
    val level = ScoreColorMapper.level(score.total)
    Card(modifier = Modifier.fillMaxWidth()) {
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

            SubScoreRow(
                pronunciation = score.pronunciation,
                fluency = score.fluency,
                completeness = score.completeness
            )

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

@Composable
private fun SubScoreRow(pronunciation: Double, fluency: Double, completeness: Double) {
    Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        SubScorePill("发音", pronunciation, Modifier.weight(1f))
        SubScorePill("流利度", fluency, Modifier.weight(1f))
        SubScorePill("完整度", completeness, Modifier.weight(1f))
    }
}

@Composable
private fun SubScorePill(label: String, value: Double, modifier: Modifier = Modifier) {
    val color = ScoreColorMapper.level(value).color()
    Column(
        modifier = modifier.padding(4.dp),
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = value.toInt().toString(),
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
private fun WordChip(word: String, scoreColor: Color) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp)
    ) {
        Box(
            modifier = Modifier
                .size(10.dp)
                .background(scoreColor, CircleShape)
        )
        Spacer(Modifier.width(6.dp))
        Text(
            text = word,
            style = MaterialTheme.typography.bodyMedium,
            color = scoreColor,
            fontWeight = FontWeight.SemiBold
        )
    }
}
