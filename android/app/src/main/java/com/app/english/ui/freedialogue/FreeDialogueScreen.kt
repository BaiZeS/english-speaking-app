package com.app.english.ui.freedialogue

import android.Manifest
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
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
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
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
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.components.BilingualText
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.RecordingGuard
import com.app.english.ui.components.ScoreRing
import com.app.english.ui.components.SuggestionBlock
import com.app.english.ui.components.TapToTalkDisplay
import com.app.english.ui.components.TapToTalkRow
import com.app.english.ui.components.TapToTalkRowUi
import com.app.english.ui.player.SubScoreRow
import com.app.english.ui.theme.Spacings
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState
import kotlinx.coroutines.flow.StateFlow

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

    RecordingGuard(viewModel::stopRecordingIfActive)

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
                    // 选择器**总是**在: 它现在同时是「+ 自定义场景」的唯一入口。
                    ScenePicker(
                        scenes = state.scenes,
                        selectedId = state.selectedSceneId,
                        onSelect = viewModel::selectScene,
                        onCreateCustom = viewModel::openSceneDialog
                    )
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
                micLevel = viewModel.micLevel,
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

    // 「+ 自定义场景」: 一句场景描述 -> 202 + 轮询 -> 目录里真的出现这一行才切过去 (§3 C3)。
    if (state.isSceneDialogOpen) {
        CustomSceneDialog(
            isCreating = state.isCreatingScene,
            error = state.customSceneError,
            onDismiss = viewModel::dismissSceneDialog,
            onSubmit = viewModel::createCustomScene
        )
    }
}

/**
 * 自定义场景输入弹层: 限长 200 (与服务端 `scene_brief` 的 4..200 同一口径)。
 * 生成期间不关弹层 —— 轮询要几秒到十几秒, 关掉它学员就看不见"还在生成"和失败原因。
 */
@Composable
private fun CustomSceneDialog(
    isCreating: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onSubmit: (String) -> Unit
) {
    var brief by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = { if (!isCreating) onDismiss() },
        title = { Text("描述一个你想练的场景") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text(
                    "一句话说清场景就行, 比如「和外教聊我的周末」。AI 会把它做成一场对话。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                OutlinedTextField(
                    value = brief,
                    onValueChange = { brief = it.take(CUSTOM_SCENE_MAX_CHARS) },
                    enabled = !isCreating,
                    maxLines = 3,
                    label = { Text("场景描述") },
                    supportingText = { Text("${brief.length}/$CUSTOM_SCENE_MAX_CHARS") }
                )
                if (isCreating) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(8.dp))
                        Text("AI 正在写这个场景…", style = MaterialTheme.typography.bodySmall)
                    }
                }
                // 失败原样显示在弹层里: 目录里没有这一行, 界面就不能假装建好了。
                error?.let {
                    Text(
                        it,
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.error
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onSubmit(brief) },
                enabled = !isCreating && brief.trim().length >= CUSTOM_SCENE_MIN_CHARS
            ) { Text(if (isCreating) "生成中…" else "生成") }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !isCreating) { Text("取消") }
        }
    )
}

@Composable
private fun FreeDialogueContent(
    state: FreeDialogueUiState,
    micLevel: StateFlow<Float>,
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
                if (state.suggestedReply.isBlank()) {
                    Text(
                        // P8·2c: 没有参考回答也照常能录 —— 这里只是渲染层兜底文案。
                        "（本轮没有参考回答，直接开口说就好）",
                        style = MaterialTheme.typography.bodyLarge,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                } else {
                    // D4: 要求学员开口的那句**默认双语** —— 英文在上, 中文在下, 一眼能懂。
                    BilingualText(
                        primary = state.suggestedReply,
                        secondary = state.suggestedReplyCn,
                        modifier = Modifier.padding(top = 8.dp)
                    )
                }
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

        if (state.isSubmitting) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(20.dp))
                Spacer(Modifier.width(8.dp))
                Text("评分并生成下一轮对话...")
            }
        }
        // 自由对话按 D4 保留**点按**(一轮回答可以说到 30 秒上限, 没人按得住), 换
        // 文案诚实 + 真计时: 空闲写"30 秒后自动发送", 录中写"0:07"(最后 5 秒变
        // "0:26 · 即将自动发送"并转警示色)。这一页此前既没有电平条也没有计时, 于是
        // "点了开始回答之后界面完全不动"就是用户报的那个观感。
        // 手势节点仍然只有一个 Button(见 TapToTalkRow) —— 换控件才是旧的吞按压根因。
        TapToTalkRow(
            row = TapToTalkRowUi(
                level = micLevel,
                isRecording = state.isRecording,
                isBusy = state.isSubmitting,
                micGranted = micGranted,
                onRequestPermission = onRequestPermission,
                onStart = onStartRecording,
                onStop = onStopAndSubmit,
                display = TapToTalkDisplay(
                    startedAtMs = state.recordingStartedAtMs,
                    capMs = state.takeCapMs,
                    idle = if (state.currentScore == null) {
                        "点一下开始回答"
                    } else {
                        "点一下回答下一轮"
                    },
                    holding = "点一下结束并发送",
                    busy = "评分中…"
                )
            )
        )

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
            // D4: AI 台词英文优先、行尾「译」展开中文 (带「中文」标签, 字重/字号区别于
            // 英文正文, 别被读成第二句参考回答); 「我」气泡同理——展开的是学员那句的
            // `learner_cn`, 本轮响应里就有, 不新发请求。
            BilingualText(
                // P8·2d: 占位提示只活在这里 (渲染层)。协议层的 text 保持
                // 诚实空串, 历史回传模型时被识别失败的回合就是空。
                primary = if (message.isUser && !message.hasTranscript) {
                    "（这句没有识别到文字）"
                } else {
                    message.text
                },
                secondary = message.translation,
                collapsible = true,
                modifier = Modifier.padding(top = 4.dp)
            )
        }
    }
}

@Composable
private fun FreeScoreCard(score: ScoreResult) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                ScoreRing(score = score.total, diameter = 40.dp, strokeWidth = 5.dp)
                Text("本轮得分", style = MaterialTheme.typography.titleMedium)
            }
            SubScoreRow(score.pronunciation, score.fluency, score.completeness)
            score.suggestion?.takeIf { it.isNotBlank() }?.let { SuggestionBlock(it) }
        }
    }
}

@Composable
private fun ScenePicker(
    scenes: List<com.app.english.domain.model.DialogueScene>,
    selectedId: String,
    onSelect: (String) -> Unit,
    onCreateCustom: () -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
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
            // 首项是入口而不是一个场景: 描完的场景会作为普通行出现在同一个目录里
            // (§3 C3b: 服务端把它并进 `GET /dialogue/scenes`), 所以这里不给它单独的区。
            DropdownMenuItem(
                text = { Text("+ 自定义场景", style = MaterialTheme.typography.bodyLarge) },
                onClick = {
                    onCreateCustom()
                    expanded = false
                }
            )
            scenes.forEach { scene ->
                DropdownMenuItem(
                    text = {
                        // §3 C3b 的最终形状: 英文副标题**只属于目录行** (catalog 恒非空);
                        // 自定义行按学员自己描述的语言展示 —— 那两格服务端恒为空串, 这里也
                        // 就不给它渲染第二行 (D5: 空 = 那一行不存在, 不是"翻译成了空")。
                        // 显式按 kind 判断而不是靠"空串自动隐藏": 后者会把"自定义场景将来
                        // 多出一个英文值"变成一次静默的规则变更。
                        val english = scene.titleEn.takeIf { !scene.isCustom }
                        val englishDescription = scene.descriptionEn.takeIf { !scene.isCustom }
                        Column {
                            BilingualText(
                                primary = scene.title,
                                secondary = english,
                                primaryStyle = MaterialTheme.typography.bodyLarge
                            )
                            if (scene.description.isNotBlank()) {
                                BilingualText(
                                    primary = scene.description,
                                    secondary = englishDescription,
                                    primaryStyle = MaterialTheme.typography.bodySmall,
                                    secondaryStyle = MaterialTheme.typography.bodySmall,
                                    modifier = Modifier.padding(top = 2.dp)
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
