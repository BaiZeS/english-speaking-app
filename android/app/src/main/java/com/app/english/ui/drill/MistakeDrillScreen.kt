package com.app.english.ui.drill

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
import androidx.compose.material.icons.filled.Mic
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
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.data.local.MistakeWordEntity
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.RecordingLevelIndicator
import com.app.english.ui.components.ScoreBadge
import com.app.english.ui.player.PermissionHint
import com.app.english.ui.player.ReferenceButton
import com.app.english.ui.player.SubScoreRow
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

/**
 * Mistake/weak word drill: play the standard pronunciation, record the word,
 * submit it with category="read_word", and graduate (remove) any word that
 * scores >= 85.
 */
@OptIn(ExperimentalMaterial3Api::class, ExperimentalPermissionsApi::class)
@Composable
fun MistakeDrillScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: MistakeDrillViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)

    LaunchedEffect(state.error) {
        state.error?.let { message ->
            snackbarHostState.showSnackbar(message)
            viewModel.dismissError()
        }
    }
    LaunchedEffect(state.graduatedWord) {
        state.graduatedWord?.let { word ->
            snackbarHostState.showSnackbar("已毕业：$word")
            viewModel.dismissGraduated()
        }
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("弱词训练") },
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
            state.finished || state.words.isEmpty() -> DrillEmptyState(
                finished = state.finished,
                onBack = onBack,
                modifier = Modifier.padding(padding)
            )
            else -> DrillContent(
                state = state,
                micGranted = micPermission.status.isGranted,
                onRequestPermission = { micPermission.launchPermissionRequest() },
                onPlayDemo = viewModel::playDemo,
                onStartRecording = viewModel::startRecording,
                onStopAndScore = viewModel::stopAndScore,
                onNext = viewModel::next,
                onSkip = viewModel::skip,
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun DrillContent(
    state: MistakeDrillUiState,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onPlayDemo: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndScore: () -> Unit,
    onNext: () -> Unit,
    onSkip: () -> Unit,
    modifier: Modifier = Modifier
) {
    val word = state.currentWord ?: return
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(14.dp)
    ) {
        Text(
            text = "弱词本 · ${state.words.size} 个 · 第 ${state.currentIndex + 1} 个",
            style = MaterialTheme.typography.titleMedium
        )
        WordCard(word = word)
        ReferenceButton(
            isPlaying = state.isPlayingDemo,
            label = "听示范",
            onClick = onPlayDemo
        )
        if (!micGranted) {
            PermissionHint(onRequestPermission = onRequestPermission)
        }
        RecordingLevelIndicator(
            level = state.micLevel,
            active = state.isRecording,
            modifier = Modifier.fillMaxWidth()
        )
        DrillRecordButton(
            isRecording = state.isRecording,
            isSubmitting = state.isSubmitting,
            hasScore = state.lastScore != null,
            micGranted = micGranted,
            onRequestPermission = onRequestPermission,
            onStartRecording = onStartRecording,
            onStopAndScore = onStopAndScore
        )
        if (state.isSubmitting) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("评分中...", style = MaterialTheme.typography.bodyMedium)
            }
        }
        state.lastScore?.let { score ->
            DrillScoreCard(score = score)
            Button(onClick = onNext, modifier = Modifier.fillMaxWidth()) {
                Text("下一个")
            }
        }
        if (state.lastScore == null) {
            OutlinedButton(
                onClick = onSkip,
                modifier = Modifier.fillMaxWidth(),
                enabled = !state.isRecording && !state.isSubmitting
            ) {
                Text("跳过")
            }
        }
    }
}

@Composable
private fun DrillRecordButton(
    isRecording: Boolean,
    isSubmitting: Boolean,
    hasScore: Boolean,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndScore: () -> Unit
) {
    when {
        isSubmitting -> Button(
            onClick = {},
            modifier = Modifier.fillMaxWidth(),
            enabled = false
        ) { Text("评分中...") }
        isRecording -> Button(
            onClick = onStopAndScore,
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
            Text(if (hasScore) "重录" else "录音跟读")
        }
    }
}

@Composable
private fun WordCard(word: MistakeWordEntity) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surfaceVariant)
    ) {
        Column(
            modifier = Modifier.padding(20.dp),
            horizontalAlignment = Alignment.CenterHorizontally
        ) {
            Text(
                text = word.word,
                style = MaterialTheme.typography.headlineLarge,
                fontWeight = FontWeight.Bold
            )
            word.ipa?.takeIf { it.isNotBlank() }?.let { ipa ->
                Text(
                    text = "/$ipa/",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(top = 6.dp)
                )
            }
            Text(
                text = "上次 ${word.lastScore.toInt()} 分 · 来自 ${word.book} L${word.lessonId}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(top = 10.dp)
            )
        }
    }
}

@Composable
private fun DrillScoreCard(score: ScoreResult) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                ScoreBadge(score = score.total)
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "未达毕业标准（85 分），可重录或进入下一个词",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            SubScoreRow(score.pronunciation, score.fluency, score.completeness)
            if (score.isStub) {
                Text(
                    text = "⚠ 评分引擎未配置，当前为占位假分",
                    style = MaterialTheme.typography.bodySmall,
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
        }
    }
}

@Composable
private fun DrillEmptyState(finished: Boolean, onBack: () -> Unit, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text(
            text = if (finished) "全部完成" else "弱词本为空",
            style = MaterialTheme.typography.titleLarge
        )
        Text(
            text = if (finished) {
                "本轮弱词已全部练习完毕。"
            } else {
                "还没有弱词。完成跟读或自由对话后，得分低于 70 的词会自动收录到这里。"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp)
        )
        Button(onClick = onBack, modifier = Modifier.padding(top = 16.dp)) {
            Text("返回")
        }
    }
}
