package com.app.english.ui.assessment

import android.Manifest
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ABILITY_DIMENSIONS
import com.app.english.domain.model.AssessmentJudgement
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.RadarChart
import com.app.english.ui.components.toRadarValue
import com.app.english.ui.me.AbilityAxes
import com.app.english.ui.player.PermissionHint
import com.app.english.ui.theme.Spacings
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

/**
 * CEFR 测评三屏(计划 §6.4): 引导 -> 做题(录音或文本) -> 判级结果。
 * 文案风格对照「能力测评截图」: 大徽章 + 雷达 + 一维一句建议。
 */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AssessmentIntroScreen(
    onBack: () -> Unit,
    onStart: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AssessmentIntroViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("CEFR 能力测评") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s3)
        ) {
            IntroHero(minutes = state.estimatedMinutes, questionCount = state.questionCount)
            when {
                state.isLoading -> Box(
                    modifier = Modifier.fillMaxWidth().height(120.dp),
                    contentAlignment = Alignment.Center
                ) {
                    CircularProgressIndicator()
                }

                state.error != null -> ErrorState(
                    message = state.error ?: "题库加载失败",
                    onRetry = viewModel::loadBank
                )

                else -> IntroRules()
            }
            Button(
                onClick = onStart,
                enabled = !state.isLoading && state.error == null && state.questionCount > 0,
                modifier = Modifier.fillMaxWidth().height(52.dp)
            ) {
                Text("开始测评", style = MaterialTheme.typography.titleMedium)
            }
            Text(
                text = "判级使用 AI 批量阅卷, 交卷后约 20 秒出结果; 结果会写入你的能力画像。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun IntroHero(minutes: Int, questionCount: Int) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s4).fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Icon(
                imageVector = Icons.Filled.Explore,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onPrimaryContainer,
                modifier = Modifier.size(48.dp)
            )
            Text(
                text = "测一测你的英语水平",
                style = MaterialTheme.typography.headlineSmall,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
            Text(
                text = if (minutes >
                    0
                ) {
                    "约 $minutes 分钟 · $questionCount 道题"
                } else {
                    "$questionCount 道题"
                },
                style = MaterialTheme.typography.titleMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
        }
    }
}

@Composable
private fun IntroRules() {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            IntroRule("会用到录音与翻译", "跟读题要开麦录真音, 其他题打字或说话都行")
            IntroRule("从 A2 到 B1 逐题加深", "题目按 CEFR 难度锚排列, 答不出可以尽量说")
            IntroRule("判级后解锁四维画像", "发音 / 语法 / 词汇 / 流利度雷达 + CEFR 等级")
        }
    }
}

@Composable
private fun IntroRule(title: String, detail: String) {
    Row(verticalAlignment = Alignment.Top) {
        Text(
            text = "·",
            style = MaterialTheme.typography.titleLarge,
            color = MaterialTheme.colorScheme.primary
        )
        Column(
            modifier = Modifier.padding(start = Spacings.s1),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text(text = title, style = MaterialTheme.typography.titleSmall)
            Text(
                text = detail,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalPermissionsApi::class)
@Composable
fun AssessmentScreen(
    onBack: () -> Unit,
    onFinished: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AssessmentViewModel = hiltViewModel()
) {
    val state by viewModel.flow.collectAsStateWithLifecycle()
    val isRecording by viewModel.isRecording.collectAsStateWithLifecycle()
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)
    var answerDraft by remember { mutableStateOf("") }

    // 判级完成 -> 结果页(判级结果经 holder 交接, 路由不带载荷)。
    LaunchedEffect(state.phase) {
        if (state.phase == AssessmentPhase.DONE) onFinished()
    }

    // 翻到下一题: 清空上一题草稿(UI 与 VM 同步), 不会把旧文本带进下一题重交。
    LaunchedEffect(state.index) {
        answerDraft = ""
        viewModel.updateDraft("")
    }

    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        Text("能力测评")
                        if (state.total > 0) {
                            Text(
                                text = state.progressLabel,
                                style = MaterialTheme.typography.labelMedium,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    }
                },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        when {
            state.phase == AssessmentPhase.STARTING && state.error == null ->
                LoadingState(modifier = Modifier.padding(padding))

            state.error != null && state.total == 0 -> ErrorState(
                message = state.error ?: "开考失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::start
            )

            else -> QuestionBody(
                state = state,
                isRecording = isRecording,
                micGranted = micPermission.status.isGranted,
                onRequestMic = { micPermission.launchPermissionRequest() },
                answerDraft = answerDraft,
                onDraftChange = {
                    answerDraft = it
                    viewModel.updateDraft(it)
                },
                onSubmitText = viewModel::submitText,
                onStartRecord = viewModel::startRecording,
                onStopRecord = viewModel::stopRecordingAndSubmit,
                onPlaySample = viewModel::playSample,
                onRetryComplete = viewModel::complete,
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
            )
        }
    }
}

@Composable
private fun QuestionBody(
    state: AssessmentFlowState,
    isRecording: Boolean,
    micGranted: Boolean,
    onRequestMic: () -> Unit,
    answerDraft: String,
    onDraftChange: (String) -> Unit,
    onSubmitText: () -> Unit,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit,
    onPlaySample: (String) -> Unit,
    onRetryComplete: () -> Unit,
    modifier: Modifier = Modifier
) {
    val question = state.current
    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        LinearProgressIndicator(
            progress = if (state.total == 0) 0f else state.answeredCount.toFloat() / state.total,
            modifier = Modifier.fillMaxWidth()
        )
        if (question == null) return@Column
        QuestionCard(
            typeLabel = assessmentTypeLabel(question.type),
            anchor = question.cefrAnchor,
            prompt = question.cnPrompt,
            displayText = question.displayText,
            translation = question.translationCn,
            onPlaySample = onPlaySample
        )
        if (state.audioBlocked) {
            TranscriptUnavailableCard()
        }
        when {
            state.phase == AssessmentPhase.JUDGING -> JudgingCard(onRetryComplete)
            state.phase == AssessmentPhase.SUBMITTING -> Box(
                modifier = Modifier.fillMaxWidth().height(52.dp),
                contentAlignment = Alignment.Center
            ) {
                CircularProgressIndicator()
            }

            else -> AnswerInput(
                answerDraft = answerDraft,
                isRecording = isRecording,
                micGranted = micGranted,
                onRequestMic = onRequestMic,
                audioBlocked = state.audioBlocked,
                onDraftChange = onDraftChange,
                onSubmitText = onSubmitText,
                onStartRecord = onStartRecord,
                onStopRecord = onStopRecord
            )
        }
        state.error?.let { message ->
            Text(
                text = message,
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.error
            )
        }
    }
}

@Composable
private fun QuestionCard(
    typeLabel: String,
    anchor: String,
    prompt: String,
    displayText: String,
    translation: String,
    onPlaySample: (String) -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
            ) {
                Surface(
                    shape = RoundedCornerShape(50),
                    color = MaterialTheme.colorScheme.secondaryContainer
                ) {
                    Text(
                        text = typeLabel,
                        style = MaterialTheme.typography.labelMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                        modifier = Modifier.padding(
                            horizontal = Spacings.s2,
                            vertical = Spacings.half
                        )
                    )
                }
                Text(
                    text = "难度锚 $anchor",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Text(text = prompt, style = MaterialTheme.typography.titleSmall)
            Row(verticalAlignment = Alignment.Top) {
                Text(
                    text = displayText,
                    style = MaterialTheme.typography.titleLarge,
                    modifier = Modifier.weight(1f, fill = false)
                )
                IconButton(onClick = { onPlaySample(displayText) }) {
                    Icon(Icons.Filled.VolumeUp, contentDescription = "播放样句")
                }
            }
            if (translation.isNotBlank()) {
                Text(
                    text = translation,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

/** 400 TRANSCRIPT_UNAVAILABLE 的诚实引导: 音频没有证据就不硬收, 请改文本。 */
@Composable
private fun TranscriptUnavailableCard() {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.errorContainer.copy(alpha = 0.4f)
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text(
                text = "这段语音没能转写出文字",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
            Text(
                text = "语音转写服务暂不可用。改用文本作答吧, 内容同样计入判级。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onErrorContainer
            )
        }
    }
}

@Composable
private fun AnswerInput(
    answerDraft: String,
    isRecording: Boolean,
    micGranted: Boolean,
    onRequestMic: () -> Unit,
    audioBlocked: Boolean,
    onDraftChange: (String) -> Unit,
    onSubmitText: () -> Unit,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s2)) {
        OutlinedTextField(
            value = answerDraft,
            onValueChange = onDraftChange,
            modifier = Modifier.fillMaxWidth(),
            minLines = 2,
            placeholder = { Text("用英语说一说 / 写一写…") }
        )
        if (!micGranted && !audioBlocked) {
            PermissionHint(onRequestPermission = onRequestMic)
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            if (!audioBlocked) {
                OutlinedButton(
                    // 无权限先申请权限, 有权限才真正开麦(与弱词训练同一套口径)。
                    onClick = {
                        when {
                            isRecording -> onStopRecord()
                            micGranted -> onStartRecord()
                            else -> onRequestMic()
                        }
                    },
                    modifier = Modifier.weight(1f).height(48.dp)
                ) {
                    Icon(
                        imageVector = if (isRecording) Icons.Filled.Stop else Icons.Filled.Mic,
                        contentDescription = if (isRecording) "停止并提交" else "语音作答"
                    )
                    Text(
                        text = when {
                            isRecording -> " 停止并提交"
                            micGranted -> " 语音作答"
                            else -> " 先授予录音权限"
                        }
                    )
                }
            }
            Button(
                onClick = onSubmitText,
                enabled = answerDraft.isNotBlank(),
                modifier = Modifier.weight(1f).height(48.dp)
            ) {
                Text("提交本题")
            }
        }
    }
}

/** 判级 spinner(分钟级调用要诚实告诉用户在等什么)。 */
@Composable
private fun JudgingCard(onRetry: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.secondaryContainer
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s4).fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            CircularProgressIndicator()
            Text(
                text = "AI 正在批卷判级…",
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
            Text(
                text = "批量判级约需 20 秒, 请稍等, 不要退出页面。",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSecondaryContainer
            )
            TextButton(onClick = onRetry) {
                Text("等太久了? 点这里重试")
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AssessmentResultScreen(
    onBack: () -> Unit,
    onDone: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AssessmentResultViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("测评结果") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        val judgement = state.judgement
        when {
            state.isLoading -> LoadingState(modifier = Modifier.padding(padding))

            judgement == null -> ErrorState(
                message = "没有找到本次判级结果; 如果刚完成测评, 稍后在「我的」页查看画像。",
                modifier = Modifier.padding(padding),
                onRetry = onBack
            )

            else -> ResultBody(
                judgement = judgement,
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
            )
        }
    }
}

@Composable
private fun ResultBody(judgement: AssessmentJudgement, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        CefrBadgeCard(
            cefr = judgement.cefr,
            cefrLevel = judgement.cefrLevel,
            isStub = judgement.isStub
        )
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(Spacings.s3),
                verticalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                Text(text = "四维画像", style = MaterialTheme.typography.titleMedium)
                RadarChart(
                    values = ABILITY_DIMENSIONS.map { dimension ->
                        judgement.radarScore(dimension)?.div(100.0).toRadarValue()
                    },
                    axes = AbilityAxes.LABELS,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(Spacings.s3),
                verticalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                Text(text = "四维建议", style = MaterialTheme.typography.titleMedium)
                assessmentDimensionAdvice(judgement.dims).forEach { advice ->
                    Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                        Row(
                            modifier = Modifier.fillMaxWidth(),
                            horizontalArrangement = Arrangement.SpaceBetween
                        ) {
                            Text(text = advice.label, style = MaterialTheme.typography.titleSmall)
                            Text(
                                text = advice.score?.let { it.toInt().toString() } ?: "待补",
                                style = MaterialTheme.typography.titleSmall,
                                color = MaterialTheme.colorScheme.primary
                            )
                        }
                        Text(
                            text = advice.adviceCn,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
        if (judgement.rationaleCn.isNotBlank()) {
            Card(modifier = Modifier.fillMaxWidth()) {
                Column(
                    modifier = Modifier.padding(Spacings.s3),
                    verticalArrangement = Arrangement.spacedBy(Spacings.s1)
                ) {
                    Text(text = "判级说明", style = MaterialTheme.typography.titleSmall)
                    Text(
                        text = judgement.rationaleCn,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
    }
}

/** CEFR 大徽章(stub 判级时诚实显示未定级 + 后端给的说明)。 */
@Composable
private fun CefrBadgeCard(cefr: String?, cefrLevel: String?, isStub: Boolean) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (cefr != null) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.surfaceVariant
            }
        )
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s4).fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Surface(
                shape = RoundedCornerShape(50),
                color = if (cefr != null) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.outlineVariant
                }
            ) {
                Text(
                    text = cefr ?: cefrLevel ?: "未定级",
                    style = MaterialTheme.typography.displaySmall,
                    color = if (cefr != null) {
                        MaterialTheme.colorScheme.onPrimary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = Spacings.s4, vertical = Spacings.s2)
                )
            }
            Text(
                text = if (isStub) {
                    "这次没有完成 AI 判级, 结果不计入画像; 随时可以重新测一次。"
                } else {
                    "你的 CEFR 定级(已写入能力画像)"
                },
                style = MaterialTheme.typography.titleSmall,
                color = MaterialTheme.colorScheme.onSurface
            )
        }
    }
}
