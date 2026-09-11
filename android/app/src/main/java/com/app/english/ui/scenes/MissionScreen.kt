package com.app.english.ui.scenes

import android.Manifest
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Send
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.filled.Warning
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.TaskChip
import com.app.english.ui.components.HoldToTalkButton
import com.app.english.ui.components.RecordingGuard
import com.app.english.ui.components.RecordingWaveform
import com.app.english.ui.components.WaveformGeometry
import com.app.english.ui.theme.Spacings
import com.app.english.ui.theme.color
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState
import kotlinx.coroutines.flow.StateFlow

/**
 * 实战对话页(计划 §6.4, 聊天软件式): 顶部任务 chips 横滑 + 气泡流(AI 点按播
 * TTS / 用户气泡下嵌润色) + HUD + 底部大录音键与「要提示」。退出确认 ->
 * finish-mission -> 复盘页。
 */
@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun MissionScreen(
    onBack: () -> Unit,
    onOpenReview: (sessionId: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: MissionViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    var showExitDialog by remember { mutableStateOf(false) }
    var input by remember { mutableStateOf("") }
    val listState = rememberLazyListState()
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)

    RecordingGuard(viewModel::stopRecordingIfActive)

    LaunchedEffect(state.bubbles.size) {
        if (state.bubbles.isNotEmpty()) {
            listState.animateScrollToItem(state.bubbles.size - 1)
        }
    }
    LaunchedEffect(state.snackbar) {
        state.snackbar?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.consumeSnackbar()
        }
    }
    // 到轮次上限被服务端自动收工(§P6): 数值骨架随那一轮响应已经落库, 这里立刻交棒给
    // 复盘页 —— 那条路径以前会在同一个请求里同步写 AI 文案, 于是"一天练到自然结束"
    // 必然撞上 30s 读超时, 而这才是每日练习最常见的结束方式。
    LaunchedEffect(state.openReviewRequested) {
        if (state.openReviewRequested) {
            viewModel.consumeReviewRequest()
            onOpenReview(viewModel.sessionId)
        }
    }

    Box(modifier = modifier.fillMaxSize()) {
        Column(modifier = Modifier.fillMaxSize()) {
            MissionTopBar(
                state = state,
                onExit = {
                    // 收工在途时不再重开弹窗: 那正是重复提交的入口(§2.6 E2)。
                    if (MissionFinishGuard.canOpenExitDialog(state.isFinishing)) {
                        showExitDialog = true
                    }
                },
                onHint = viewModel::requestHint
            )
            if (state.isLoading) {
                Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                    androidx.compose.material3.CircularProgressIndicator()
                }
            } else {
                LazyColumn(
                    state = listState,
                    modifier = Modifier
                        .weight(1f)
                        .fillMaxWidth()
                        .padding(horizontal = Spacings.s2),
                    verticalArrangement = Arrangement.spacedBy(Spacings.s2)
                ) {
                    items(state.bubbles, key = { bubble ->
                        "${bubble.javaClass.simpleName}-${bubble.turnIndex}-${bubble.hashCode()}"
                    }) { bubble ->
                        BubbleRow(bubble, onPlayAi = viewModel::playAiBubble, onCollect = {
                            viewModel.collectPolish(it)
                        })
                    }
                    state.error?.let { message ->
                        item {
                            Text(
                                text = message,
                                color = MaterialTheme.colorScheme.error,
                                style = MaterialTheme.typography.bodySmall,
                                modifier = Modifier.padding(Spacings.s1)
                            )
                        }
                    }
                }
            }
            state.hint?.let { hint -> HintCard(hint, viewModel::dismissHint) }
            if (!state.finished) {
                InputBar(
                    input = input,
                    isRecording = state.isRecording,
                    isSubmitting = state.isSubmitting,
                    waveform = viewModel.waveform,
                    micGranted = micPermission.status.isGranted,
                    onRequestPermission = { micPermission.launchPermissionRequest() },
                    suggestion = state.suggestion,
                    onInputChange = {
                        input = it
                        viewModel.updateDraft(it)
                    },
                    onSend = {
                        viewModel.sendText()
                        input = ""
                    },
                    onStartRecord = viewModel::startRecording,
                    onStopRecord = viewModel::stopRecordingAndSend
                )
            }
        }
        SnackbarHost(
            hostState = snackbarHostState,
            modifier = Modifier.align(Alignment.BottomCenter)
        )
    }

    if (showExitDialog) {
        AlertDialog(
            onDismissRequest = {
                // 在途时不许用返回键关掉: 关掉就等于"刚刚那一下没发生", 而它可能已经
                // 发出去了 —— 学员会再点一次。
                if (!state.isFinishing) showExitDialog = false
            },
            title = { Text("收工并看复盘?") },
            text = {
                Text(
                    // 发一轮还在评分时确认键是**disabled** 的, 那就必须解释为什么按不动 ——
                    // 一灰了的键没有说明, 读起来跟"按钮坏了"一模一样。
                    if (state.inFlight && !state.isFinishing) {
                        "这一轮还在评分, 等它判完就能收工。"
                    } else {
                        "现在退出会按当前进度记下本场成绩, AI 写的总评在复盘页里补齐。"
                    }
                )
            },
            confirmButton = {
                TextButton(
                    // 收工在途时按钮**不可点**(§2.6 E2): 弹窗此刻唯一诚实的内容是这句
                    // "正在收工…"。VM 入口那道 `inFlight` 守卫是第二层, 防的是竞态。
                    enabled = !state.inFlight,
                    onClick = {
                        showExitDialog = false
                        viewModel.finishAndReview(onOpenReview)
                    }
                ) {
                    Text(if (state.isFinishing) "收工中…" else "收工")
                }
            },
            dismissButton = {
                TextButton(
                    onClick = { showExitDialog = false },
                    enabled = !state.isFinishing
                ) { Text("继续聊") }
            }
        )
    }
    // 收工真的失败了才出现的显式出口(§2.6 E2 后半)。两条都是必要的:
    // 「重试收工」处理"服务端没做成"; 「先去看复盘」处理"服务端做完了, 只是响应没回来"
    // —— 后者在这条链路上是**多数**情况(§2 问题 5 的那场生产事故就是它)。
    state.finishError?.takeIf { !state.isFinishing }?.let { message ->
        AlertDialog(
            onDismissRequest = { viewModel.dismissFinishError() },
            title = { Text("收工没成功") },
            text = { Text(message) },
            confirmButton = {
                TextButton(onClick = { viewModel.finishAndReview(onOpenReview) }) {
                    Text("重试收工")
                }
            },
            dismissButton = {
                TextButton(onClick = { viewModel.openReviewAfterFailure(onOpenReview) }) {
                    Text("先去看复盘")
                }
            }
        )
    }
}

@Composable
private fun MissionTopBar(state: MissionUiState, onExit: () -> Unit, onHint: () -> Unit) {
    Surface(shadowElevation = 2.dp) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(horizontal = Spacings.s2, vertical = Spacings.s1),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                TextButton(onClick = onExit) { Text("← 退出") }
                Text(state.hudText, style = MaterialTheme.typography.labelMedium)
                TextButton(onClick = onHint) {
                    Icon(
                        Icons.Filled.Warning,
                        contentDescription = null,
                        tint = if (state.hintWarnsScore) {
                            MaterialTheme.colorScheme.tertiary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        },
                        modifier = Modifier.size(16.dp)
                    )
                    Text("要提示")
                }
            }
            if (state.personaCn.isNotBlank()) {
                Text(
                    text = "对方是${state.personaCn}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            LazyRow(horizontalArrangement = Arrangement.spacedBy(Spacings.s1)) {
                items(state.checklist, key = { it.id }) { task ->
                    TaskChipView(task)
                }
            }
        }
    }
}

@Composable
private fun TaskChipView(task: TaskChip) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (task.done) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Row(
            modifier = Modifier.padding(horizontal = Spacings.s2, vertical = Spacings.tiny),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = if (task.done) "✓" else "○",
                color = if (task.done) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.onSurfaceVariant
                }
            )
            Box(Modifier.size(Spacings.tiny))
            Text(
                text = task.descCn + if (task.required) "" else " (选做)",
                style = MaterialTheme.typography.labelMedium
            )
        }
    }
}

@Composable
private fun BubbleRow(
    bubble: MissionBubble,
    onPlayAi: (String) -> Unit,
    onCollect: (com.app.english.domain.model.PolishSuggestion) -> Unit
) {
    when (bubble) {
        is MissionBubble.Ai -> Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.Start
        ) {
            BubbleCard(
                text = bubble.text,
                container = MaterialTheme.colorScheme.surfaceVariant,
                content = MaterialTheme.colorScheme.onSurfaceVariant,
                onClick = { onPlayAi(bubble.text) }
            )
        }
        is MissionBubble.User -> Column(
            modifier = Modifier.fillMaxWidth(),
            horizontalAlignment = Alignment.End
        ) {
            BubbleCard(
                text = if (bubble.hasTranscript) bubble.text else "(这句没有识别到文字)",
                container = MaterialTheme.colorScheme.primaryContainer,
                content = MaterialTheme.colorScheme.onPrimaryContainer,
                onClick = null
            )
            bubble.speech?.let { strip -> SpeechStripRow(strip) }
            bubble.polish?.let { polish -> PolishInlineCard(polish, onCollect) }
        }
    }
}

/**
 * 逐轮发音条。
 *
 * 后端每轮都发 `sub_scores`/`speech_rate_wpm`, 以前映射层丢掉 -> 实战语音说完听不到任何
 * 发音反馈(与打基础同一个病)。这里刻意做得很扁: 实战一屏 6-12 轮, 每轮铺开一张反馈卡
 * 会把对话本身挤没, 所以只留"哪个维度低、说多快、哪几个词没读准"。配色与打基础同源。
 */
@Composable
private fun SpeechStripRow(strip: SpeechStrip) {
    Column(
        modifier = Modifier.fillMaxWidth(),
        horizontalAlignment = Alignment.End,
        verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
    ) {
        Row(horizontalArrangement = Arrangement.spacedBy(Spacings.s1)) {
            strip.dims.forEach { dim ->
                Text(
                    text = "${dim.label} ${dim.score.toInt()}",
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = ScoreColorMapper.level(dim.score).color()
                )
            }
            strip.rateLabel?.let { rate ->
                Text(
                    text = rate,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
        if (strip.weakWords.isNotEmpty()) {
            Text(
                text = "没读准：${strip.weakWords.joinToString("、")}",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.error
            )
        }
    }
}

@Composable
private fun BubbleCard(
    text: String,
    container: androidx.compose.ui.graphics.Color,
    content: androidx.compose.ui.graphics.Color,
    onClick: (() -> Unit)?
) {
    Surface(
        color = container,
        contentColor = content,
        shape = RoundedCornerShape(16.dp),
        onClick = onClick ?: {},
        enabled = onClick != null,
        modifier = Modifier.widthIn(max = 300.dp)
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyMedium,
            modifier = Modifier.padding(Spacings.s2)
        )
    }
}

/** 润色嵌在用户气泡下: 折叠「让这句话更地道」, 展开=原句删除线/润色句+解释+⭐。 */
@Composable
private fun PolishInlineCard(
    polish: PolishBubble,
    onCollect: (com.app.english.domain.model.PolishSuggestion) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surface
        ),
        onClick = { expanded = !expanded }
    ) {
        Column(
            modifier = Modifier
                .padding(Spacings.s2)
                .animateContentSize(),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text(
                text = if (expanded) "让这句话更地道 ▲" else "让这句话更地道 ▼",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.primary
            )
            if (expanded) {
                Text(
                    text = polish.original,
                    style = MaterialTheme.typography.bodySmall,
                    textDecoration = TextDecoration.LineThrough,
                    color = MaterialTheme.colorScheme.error
                )
                Text(
                    text = polish.polished,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.tertiary
                )
                if (polish.explanationCn.isNotBlank()) {
                    Text(
                        text = polish.explanationCn,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
                IconButton(onClick = {
                    onCollect(polish.toSuggestion())
                }, modifier = Modifier.size(32.dp)) {
                    Icon(
                        Icons.Filled.Star,
                        contentDescription = "收进表达库",
                        tint = MaterialTheme.colorScheme.tertiary
                    )
                }
            }
        }
    }
}

private fun PolishBubble.toSuggestion(): com.app.english.domain.model.PolishSuggestion =
    com.app.english.domain.model.PolishSuggestion(
        original = original,
        polished = polished,
        explanationCn = explanationCn
    )

@Composable
private fun HintCard(hint: com.app.english.domain.model.HintData, onDismiss: () -> Unit) {
    Card(
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = Spacings.s2),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.tertiaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Row(horizontalArrangement = Arrangement.spacedBy(Spacings.s1)) {
                Text("提示", style = MaterialTheme.typography.labelMedium)
                Text(
                    text = "用提示会影响下一轮的评分可信度",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
            }
            if (hint.hintEn.isNotBlank()) {
                Text(hint.hintEn, style = MaterialTheme.typography.bodyMedium)
            }
            if (hint.scriptLine.isNotBlank()) {
                Text(hint.scriptLine, style = MaterialTheme.typography.bodyMedium)
            }
            if (hint.noteCn.isNotBlank()) {
                Text(
                    text = hint.noteCn,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
            }
            TextButton(onClick = onDismiss) { Text("知道了") }
        }
    }
}

@Composable
private fun InputBar(
    input: String,
    isRecording: Boolean,
    isSubmitting: Boolean,
    waveform: StateFlow<List<Float>>,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    suggestion: String,
    onInputChange: (String) -> Unit,
    onSend: () -> Unit,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .padding(Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        if (suggestion.isNotBlank()) {
            Text(
                text = "试试这么说：$suggestion",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        // 波形在输入框上方独立一行: 它比按钮更需要"看得见", 而按钮是嵌在输入行里的
        // 行内小话筒(与输入框/发送键同一个 Row), 所以这里不套 HoldToTalkRow。
        RecordingWaveform(
            waveform = waveform,
            presentation = WaveformGeometry.presentation(isRecording, isSubmitting)
        )
        Row(
            verticalAlignment = Alignment.Bottom,
            horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            OutlinedTextField(
                value = input,
                onValueChange = onInputChange,
                modifier = Modifier.weight(1f),
                placeholder = { Text("打字, 或按住右边话筒说话") },
                maxLines = 3
            )
            HoldToTalkButton(
                isRecording = isRecording,
                enabled = !isSubmitting,
                micGranted = micGranted,
                onRequestPermission = onRequestPermission,
                onStart = onStartRecord,
                onStop = onStopRecord,
                buttonSize = 56.dp,
                iconSize = 26.dp
            )
            IconButton(onClick = onSend, enabled = input.isNotBlank() && !isSubmitting) {
                Icon(
                    Icons.Filled.Send,
                    contentDescription = "发送",
                    tint = MaterialTheme.colorScheme.primary
                )
            }
        }
    }
}
