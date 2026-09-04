package com.app.english.ui.scenes

import androidx.compose.animation.animateContentSize
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
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.DrillGradeResult
import com.app.english.domain.model.FoundationStepSpec
import com.app.english.ui.components.RecordingLevelIndicator
import com.app.english.ui.theme.Spacings

/**
 * 打基础页(计划 §6.4): 顶部 step 进度点(f1..fN) + 按题型换卡片 +
 * 底部跳过。60 分以下不拦(可重录), 只用警示色; 跳过额度用完前置禁用。
 */
@Composable
fun BriefingScreen(
    onBack: () -> Unit,
    onOpenMission: (sessionId: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: BriefingViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val isRecording by viewModel.isRecording.collectAsStateWithLifecycle()
    val isPlayingRef by viewModel.isPlayingRef.collectAsStateWithLifecycle()
    var draft by remember { mutableStateOf("") }

    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacings.s3),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
            TextButton(onClick = onBack) { Text("← 退出") }
            Text(
                text = "跳过额度 ${state.skipsRemaining}/${state.skipLimit}",
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        ProgressDots(state)
        state.error?.let { message -> ErrorBanner(message, viewModel::dismissError) }
        StepCard(
            spec = viewModel.currentSpec(),
            state = state,
            isRecording = isRecording,
            isPlayingRef = isPlayingRef,
            draft = draft,
            onDraftChange = {
                draft = it
                viewModel.updateDraft(it)
            },
            onPlayReference = viewModel::playReference,
            onStartRecord = viewModel::startRecording,
            onStopRecord = viewModel::stopRecordingAndSubmit,
            onSubmitText = viewModel::submitText
        )
        if (state.unlockedMission) {
            Button(
                onClick = { onOpenMission(viewModel.sessionId) },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) { Text("打基础完成, 进入实战对话") }
        } else {
            OutlinedButton(
                onClick = viewModel::skipCurrent,
                enabled = state.canSkip,
                modifier = Modifier.fillMaxWidth()
            ) {
                Text(if (state.canSkip) "跳过这一步" else "跳过额度已用完")
            }
        }
    }
}

@Composable
private fun ErrorBanner(message: String, onDismiss: () -> Unit) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer
        )
    ) {
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer,
                modifier = Modifier.weight(1f)
            )
            TextButton(onClick = onDismiss) { Text("知道了") }
        }
    }
}

/** f1..fN 进度点: 过关实心打勾 / 跳过打叉位 / 当前高亮圈 / 未做灰。 */
@Composable
private fun ProgressDots(state: BriefingUiState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1),
        verticalAlignment = Alignment.CenterVertically
    ) {
        state.steps.forEachIndexed { index, step ->
            val isCurrent = index == state.currentIndex
            val container = when {
                step.status == "passed" -> MaterialTheme.colorScheme.primary
                isCurrent -> MaterialTheme.colorScheme.tertiary
                step.status == "skipped" -> MaterialTheme.colorScheme.secondaryContainer
                else -> MaterialTheme.colorScheme.surfaceVariant
            }
            Box(
                modifier = Modifier
                    .size(30.dp)
                    .background(color = container, shape = CircleShape),
                contentAlignment = Alignment.Center
            ) {
                if (step.status == "passed") {
                    Icon(
                        imageVector = Icons.Filled.Check,
                        contentDescription = "已过关",
                        tint = MaterialTheme.colorScheme.onPrimary,
                        modifier = Modifier.size(18.dp)
                    )
                } else {
                    Text(
                        text = "${index + 1}",
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

@Composable
private fun StepCard(
    spec: FoundationStepSpec?,
    state: BriefingUiState,
    isRecording: Boolean,
    isPlayingRef: Boolean,
    draft: String,
    onDraftChange: (String) -> Unit,
    onPlayReference: (String) -> Unit,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit,
    onSubmitText: () -> Unit
) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface)
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s3)
                .animateContentSize(),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            if (spec == null) {
                Text(
                    text = if (state.steps.isEmpty()) "正在恢复会话…" else "全部步骤已完成",
                    style = MaterialTheme.typography.bodyMedium
                )
                return@Column
            }
            Text(spec.cnPrompt, style = MaterialTheme.typography.titleMedium)
            when (spec.type) {
                "read_along" -> ReadAlongBody(
                    spec = spec,
                    isPlayingRef = isPlayingRef,
                    onPlayReference = onPlayReference
                )
                "translate" -> TranslateBody(
                    spec = spec,
                    draft = draft,
                    onDraftChange = onDraftChange
                )
                "retell" -> RetellBody(
                    spec = spec,
                    isPlayingRef = isPlayingRef,
                    onPlayReference = onPlayReference,
                    draft = draft,
                    onDraftChange = onDraftChange
                )
                else -> MakeSentenceBody(spec = spec, draft = draft, onDraftChange = onDraftChange)
            }
            RecordButtonRow(
                isRecording = isRecording,
                isSubmitting = state.isSubmitting,
                onStartRecord = onStartRecord,
                onStopRecord = onStopRecord
            )
            if (spec.type != "read_along") {
                Button(
                    onClick = onSubmitText,
                    enabled = !state.isSubmitting && draft.isNotBlank(),
                    modifier = Modifier.fillMaxWidth()
                ) { Text("提交文字作答") }
            }
            state.lastGrade
                ?.takeIf { state.answeredStepId == spec.id || state.currentStep == null }
                ?.let { grade -> GradeResultCard(grade) }
        }
    }
}

/** 跟读: 现染色样式的大字原句 + 播音 + 大录音键(ISE 逐词分)。 */
@Composable
private fun ReadAlongBody(
    spec: FoundationStepSpec,
    isPlayingRef: Boolean,
    onPlayReference: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        Text(spec.refText, style = MaterialTheme.typography.titleLarge)
        if (spec.translationCn.isNotBlank()) {
            Text(
                text = spec.translationCn,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        TextButton(onClick = { onPlayReference(spec.refText) }, enabled = !isPlayingRef) {
            Icon(Icons.Filled.PlayArrow, contentDescription = null)
            Text(if (isPlayingRef) "播放中…" else "听原句")
        }
        if (spec.acceptNotes.isNotBlank()) {
            Text(
                text = "评分要点：${spec.acceptNotes}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** 翻译: 中文题干 + 文本框主路径(语音可选走下方录音键)。 */
@Composable
private fun TranslateBody(
    spec: FoundationStepSpec,
    draft: String,
    onDraftChange: (String) -> Unit
) {
    OutlinedTextField(
        value = draft,
        onValueChange = onDraftChange,
        modifier = Modifier.fillMaxWidth(),
        placeholder = { Text("用英文说出这句话…") },
        minLines = 2
    )
    if (spec.targetWord.isNotBlank()) {
        Text(
            text = "要用上：${spec.targetWord}",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/** 复述: 参考材料摘要折叠 + 大录音键, 文本作答备选。 */
@Composable
private fun RetellBody(
    spec: FoundationStepSpec,
    isPlayingRef: Boolean,
    onPlayReference: (String) -> Unit,
    draft: String,
    onDraftChange: (String) -> Unit
) {
    var expanded by remember { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        TextButton(onClick = { expanded = !expanded }) {
            Text(if (expanded) "收起参考材料" else "看参考材料")
        }
        if (expanded) {
            Text(spec.refText, style = MaterialTheme.typography.bodyLarge)
            if (spec.translationCn.isNotBlank()) {
                Text(
                    text = spec.translationCn,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            TextButton(onClick = { onPlayReference(spec.refText) }, enabled = !isPlayingRef) {
                Icon(Icons.Filled.PlayArrow, contentDescription = null)
                Text(if (isPlayingRef) "播放中…" else "听一遍")
            }
        }
        OutlinedTextField(
            value = draft,
            onValueChange = onDraftChange,
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("不方便开口? 也可以打字复述…") },
            minLines = 2
        )
    }
}

/** 造句: 目标词卡 + 参考句折叠 + 录音/文本。 */
@Composable
private fun MakeSentenceBody(
    spec: FoundationStepSpec,
    draft: String,
    onDraftChange: (String) -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
        ) {
            Box(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(Spacings.s2)
            ) {
                Text(
                    text = spec.targetWord,
                    style = MaterialTheme.typography.headlineMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
            }
        }
        if (spec.acceptNotes.isNotBlank()) {
            Text(
                text = "评分要点：${spec.acceptNotes}",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
    OutlinedTextField(
        value = draft,
        onValueChange = onDraftChange,
        modifier = Modifier.fillMaxWidth(),
        placeholder = { Text("用 ${spec.targetWord} 造一句…") },
        minLines = 2
    )
}

@Composable
private fun RecordButtonRow(
    isRecording: Boolean,
    isSubmitting: Boolean,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        RecordingLevelIndicator(level = if (isRecording) 0.7f else 0f, active = isRecording)
        Row(verticalAlignment = Alignment.CenterVertically) {
            FilledIconButton(
                onClick = if (isRecording) onStopRecord else onStartRecord,
                enabled = !isSubmitting,
                modifier = Modifier.size(72.dp),
                shape = CircleShape,
                colors = IconButtonDefaults.filledIconButtonColors(
                    containerColor = if (isRecording) {
                        MaterialTheme.colorScheme.error
                    } else {
                        MaterialTheme.colorScheme.primary
                    }
                )
            ) {
                Icon(
                    imageVector = Icons.Filled.Mic,
                    contentDescription = if (isRecording) "停止录音" else "开始录音",
                    tint = MaterialTheme.colorScheme.onPrimary,
                    modifier = Modifier.size(32.dp)
                )
            }
            Spacer1()
            Text(
                text = when {
                    isSubmitting -> "评分中…"
                    isRecording -> "松开完成录音"
                    else -> "按住说话 / 或打字作答"
                },
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun Spacer1() {
    Box(Modifier.size(Spacings.s2))
}

/** 评分结果卡: 分数 + 反馈 + 误译/要点; 非真实评分挂警示。 */
@Composable
private fun GradeResultCard(grade: DrillGradeResult) {
    Card(
        colors = CardDefaults.cardColors(
            containerColor = if (grade.passed) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = "${grade.score.toInt()} 分",
                    style = MaterialTheme.typography.headlineSmall,
                    color = if (grade.passed) {
                        MaterialTheme.colorScheme.onPrimaryContainer
                    } else {
                        MaterialTheme.colorScheme.error
                    }
                )
                Box(Modifier.size(Spacings.s1))
                Text(
                    text = if (grade.passed) "过关" else "未到 ${grade.passScore.toInt()} 分, 可以再试一次",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (!grade.isRealEvidence) {
                Text(
                    text = "本轮为离线占位评分 (${grade.source}), 不计入能力画像",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            }
            if (grade.feedbackCn.isNotBlank()) {
                Text(grade.feedbackCn, style = MaterialTheme.typography.bodyMedium)
            }
            grade.keyPointsHit.forEach { hit ->
                Text(
                    text = "✓ $hit",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            }
            grade.mistakes.forEach { mistake ->
                Column {
                    Text(
                        text = mistake.said,
                        style = MaterialTheme.typography.bodySmall,
                        textDecoration = TextDecoration.LineThrough,
                        color = MaterialTheme.colorScheme.error
                    )
                    Text(
                        text = "${mistake.better} — ${mistake.explanationCn}",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.tertiary
                    )
                }
            }
        }
    }
}
