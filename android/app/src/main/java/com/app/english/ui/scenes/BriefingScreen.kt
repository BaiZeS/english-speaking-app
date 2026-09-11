package com.app.english.ui.scenes

import android.Manifest
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.ScrollState
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.snapshotFlow
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerInputScope
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.FoundationStepSpec
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.HoldToTalkCopy
import com.app.english.ui.components.HoldToTalkRow
import com.app.english.ui.components.HoldToTalkRowUi
import com.app.english.ui.components.RecordingGuard
import com.app.english.ui.theme.Spacings
import com.app.english.ui.theme.color
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.distinctUntilChanged

/**
 * 打基础页(计划 §6.4): 顶部 step 进度点(f1..fN) + 按题型换卡片 +
 * 底部跳过。60 分以下不拦(可重录), 只用警示色; 跳过额度用完前置禁用。
 *
 * 每一步作答后由 [DrillFeedbackCard] 给出完整反馈(问题 4)。反馈停留期间整屏的作答
 * 入口收起、跳过行让位, 因为那时屏幕上显示的是**刚答过**的那一题, 而服务端只接受
 * 下一个 pending 步。
 */
@OptIn(ExperimentalPermissionsApi::class)
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
    // 文本草稿按"屏幕上这一题"存, 而不是按"服务端游标指的那一题": 反馈停留期间
    // displayedStepId 还指着刚答过的那题, 确认之后才翻成下一题。换题的这一刻必须同时
    // 把 ViewModel 里的旧草稿擦掉 —— `submitText()` 读的是 ViewModel 那一份, 擦不干净
    // 就是"输入框显示新题、提交上去是上一题的句子"。
    var draft by remember(state.displayedStepId) { mutableStateOf("") }
    LaunchedEffect(state.displayedStepId) { viewModel.updateDraft(draft) }
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)

    RecordingGuard(viewModel::stopRecordingIfActive)

    val scrollState = FeedbackCountdownWiring(viewModel, state.autoAdvanceSeconds)

    Column(
        modifier = modifier
            .fillMaxSize()
            .pointerInput(Unit) { cancelOnAnyTap(onTap = viewModel::cancelAutoAdvance) }
            .verticalScroll(scrollState)
            .padding(Spacings.s3),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        SkipQuotaRow(state = state, onBack = onBack)
        ProgressDots(state)
        // 快照没到手时由下面的 ErrorState 承担(带「重试」), 不再叠一条只能「知道了」
        // 的横幅 —— 同一个错误说两遍, 且其中一遍没有出路。
        state.error
            ?.takeUnless { state.needsSnapshotRetry }
            ?.let { message -> ErrorBanner(message, viewModel::dismissError) }
        if (state.needsSnapshotRetry) {
            // 快照压根没到手: 这一屏无事可做, 给「重试」而不是永远亮着的题目卡。
            ErrorState(
                message = state.emptyStepsExplanation,
                onRetry = viewModel::restore
            )
        } else {
            StepCard(
                spec = viewModel.currentSpec(),
                state = state,
                isRecording = isRecording,
                waveform = viewModel.waveform,
                micGranted = micPermission.status.isGranted,
                onRequestPermission = { micPermission.launchPermissionRequest() },
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
            state.pendingGrade?.let { grade ->
                DrillFeedbackCard(
                    DrillFeedbackUi(
                        grade = grade,
                        canRetry = state.canRetryAnsweredStep,
                        autoAdvanceHint = state.autoAdvanceHint,
                        onRetry = viewModel::acknowledgeFeedback,
                        onContinue = viewModel::acknowledgeFeedback
                    )
                )
            }
        }
        when {
            state.unlockedMission -> Button(
                onClick = { onOpenMission(viewModel.sessionId) },
                modifier = Modifier
                    .fillMaxWidth()
                    .height(52.dp)
            ) { Text("打基础完成, 进入实战对话") }

            // 清单还没到手就不渲染这一行: 以前它会在加载失败时永久宣称
            // "跳过额度已用完", 而同屏右上角还印着 "跳过额度 2/2"。
            // 反馈停留时也不渲染: 那时可跳的下一步并没有显示在屏幕上。
            state.showsSkipRow && !state.isAwaitingFeedback -> OutlinedButton(
                onClick = viewModel::skipCurrent,
                enabled = state.canSkip,
                modifier = Modifier.fillMaxWidth()
            ) { Text(state.skipLabel) }
        }
    }
}

/** 顶行: 退出 + 跳过额度。额度数字与下面的跳过键文案同源([BriefingUiState.skipLabel])。 */
@Composable
private fun SkipQuotaRow(state: BriefingUiState, onBack: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.SpaceBetween
    ) {
        TextButton(onClick = onBack) { Text("← 退出") }
        Text(
            text = "跳过额度 ${state.skipsRemaining}/${state.skipLimit}",
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

/**
 * 反馈停留期间的倒计时接线: 秒针 + 两个取消源(滚动 / 点按)。抽出来是为了让"什么会
 * 撤掉自动前进"一眼看全, 也不用把 [BriefingScreen] 的正文撑肥。
 *
 * 秒针的键就是剩余秒数, 每秒重挂一次 delay, 走到 null(确认 / 取消)自然停 —— 放在界面层
 * 而不是 ViewModel 的常驻协程里, 是为了"这一屏不在前台就绝不翻篇": 反馈被抽走的最坏
 * 形态, 是人在别处、页却自己往前走。返回的 [ScrollState] 由调用方挂到整页滚动上, 滚动
 * 事件在这里变成一个取消动作。
 */
@Composable
private fun FeedbackCountdownWiring(viewModel: BriefingViewModel, secondsLeft: Int?): ScrollState {
    val scrollState = rememberScrollState()
    LaunchedEffect(secondsLeft) {
        if (secondsLeft == null) return@LaunchedEffect
        delay(FeedbackAdvancePolicy.TICK_MILLIS)
        viewModel.tickAutoAdvance()
    }
    // [D10] 滚动 = "我要自己掌握阅读节奏" -> 只撤倒计时, 反馈留在屏上。
    LaunchedEffect(scrollState) {
        snapshotFlow { scrollState.isScrollInProgress }
            .distinctUntilChanged()
            .collect { scrolling -> if (scrolling) viewModel.cancelAutoAdvance() }
    }
    return scrollState
}

/**
 * 整屏"任意点按都算取消", **包括落在子按键上的那一次**。
 *
 * 不用 `detectTapGestures` 是因为 clickable 在 Main pass 消费按压并阻断传播, 父层的探测
 * 永远收不到落在「听原句」/文本框/展开键上的那几下 —— 而 D10 说的"点按任意处"里, 最典型
 * 的恰恰是这些: 正在读反馈的人就是要重听一遍、要改一下草稿。这里在 Initial pass 观察同
 * 一次按压, **只看不动**, 所以子节点行为完全不受影响。
 *
 * 位移超过 touch slop 的那次按滚动处理(由 `isScrollInProgress` 那条路取消), 回弹/甩动
 * 因此不会被当成点按。「继续」/「再试一次」被点到也只是先撤秒针、再自己清掉 pendingGrade,
 * 终态一致。
 */
private suspend fun PointerInputScope.cancelOnAnyTap(onTap: () -> Unit) {
    // 两边同为像素: `touchSlop` 与 `PointerInputChange.position` 都是 px, 所以这里
    // 平方一下直接比, 不要绕去 Dp —— 绕一圈只会把 density 悄悄乘进去。
    val slopSquared = viewConfiguration.touchSlop.let { it * it }
    awaitEachGesture {
        val down = awaitFirstDown(requireUnconsumed = false, pass = PointerEventPass.Initial)
        var dragged = false
        var finished = false
        // 循环节抄 HoldToTalkButton 的 drainUntilUp: 以"这根手指抬手"为一次手势的终点,
        // 而不是"当前没有任何按下"—— 多指时后者会提前退出, 把 awaitEachGesture 的流打乱。
        while (!finished) {
            val event = awaitPointerEvent(PointerEventPass.Initial)
            for (change in event.changes) {
                if (change.pressed) {
                    val delta = change.position - change.previousPosition
                    if (delta.x * delta.x + delta.y * delta.y > slopSquared) dragged = true
                } else if (change.id == down.id) {
                    finished = true
                }
            }
        }
        if (!dragged) onTap()
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

/**
 * f1..fN 进度点: 过关实心打勾 / 跳过打叉位 / 当前高亮圈 / 未做灰。
 *
 * 分数本来就在状态里(`bestScore`/`lastScore`/`attempts` 服务端逐步都给了), 以前这一排
 * 只画序号和一个勾 —— 于是"这一步我读过三次、最好 92 分"和"一次过 61 分"长得一模一样。
 * 现在有点就报分并按分数带配色, 只有没作答过的步才退回序号/勾。
 */
@Composable
private fun ProgressDots(state: BriefingUiState) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1),
        verticalAlignment = Alignment.Top
    ) {
        state.steps.forEachIndexed { index, step ->
            // 高亮跟着**屏幕上这一题**走, 不是服务端游标: 反馈停留时游标已经在下一题,
            // 若还按游标画, 屏幕讲上一题、进度点标下一题, 两处各说各话。
            val isCurrent = step.id == state.displayedStepId
            val score = step.dotScore
            val container = when {
                score != null -> ScoreColorMapper.level(score).color()
                step.status == "passed" -> MaterialTheme.colorScheme.primary
                isCurrent -> MaterialTheme.colorScheme.tertiary
                step.status == "skipped" -> MaterialTheme.colorScheme.secondaryContainer
                else -> MaterialTheme.colorScheme.surfaceVariant
            }
            Column(
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
            ) {
                Box(
                    modifier = Modifier
                        .size(DOT_SIZE)
                        .background(color = container, shape = CircleShape),
                    contentAlignment = Alignment.Center
                ) {
                    when {
                        score != null -> Text(
                            text = score.toInt().toString(),
                            style = MaterialTheme.typography.labelMedium,
                            color = Color.White,
                            fontWeight = FontWeight.Bold
                        )
                        step.status == "passed" -> Icon(
                            imageVector = Icons.Filled.Check,
                            contentDescription = "已过关",
                            tint = MaterialTheme.colorScheme.onPrimary,
                            modifier = Modifier.size(18.dp)
                        )
                        else -> Text(
                            text = "${index + 1}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                // 占位保持整排点对齐: 没刷过第二次也要留这一行的高度。
                Text(
                    text = step.dotAttempts.orEmpty(),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun StepCard(
    spec: FoundationStepSpec?,
    state: BriefingUiState,
    isRecording: Boolean,
    waveform: StateFlow<List<Float>>,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
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
                    text = state.emptyStepsExplanation,
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
            // 作答键只在"屏幕上这一题正好就是待做步"时摆出来(见 answerableStepId):
            // 过关停留时屏上是已答完的那一题, 发过去只会吃 409; 而不及格与崩溃恢复的
            // 停留屏上就是待做步 —— 那时反馈和录音键并存才对, 「再试一次」不必先确认。
            if (state.answerableStepId != null) {
                RecordButtonRow(
                    isRecording = isRecording,
                    isSubmitting = state.isSubmitting,
                    waveform = waveform,
                    micGranted = micGranted,
                    onRequestPermission = onRequestPermission,
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
                GradingIndicator(state.isSubmitting)
            }
        }
    }
}

/**
 * 在途指示: 真转圈 + 一句话。
 *
 * 以前唯一的"还在算"证据是 `HoldToTalkRow` 那侧的一行文字。文本步走 LLM judge(最坏
 * ~40s, 已超手机 30s 读超时), 学员看不见任何进度就只能反复点。范式抄自
 * `PlayerScreen` 的同一段。话术在这里置空([RecordButtonRow]): 同一屏不该把"评分中"
 * 说两遍, 而底部那个被禁用的跳过键写的是**为什么禁用**, 是另一件事。
 */
@Composable
private fun GradingIndicator(show: Boolean) {
    if (!show) return
    Row(verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(modifier = Modifier.size(SPINNER_SIZE))
        Spacer(Modifier.width(Spacings.s1))
        Text("评分中…", style = MaterialTheme.typography.bodyMedium)
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

/**
 * 打基础步的录音行 —— 就是共享的 [HoldToTalkRow], 只带这一屏自己的话术: 这一屏
 * **同时**允许打字作答, 所以空闲文案必须把两条路都说出来(旧文案写"按住说话 / 或
 * 打字作答"却配了个 onClick 点按按钮, 正是问题 1 的原文)。
 */
@Composable
private fun RecordButtonRow(
    isRecording: Boolean,
    isSubmitting: Boolean,
    waveform: StateFlow<List<Float>>,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStartRecord: () -> Unit,
    onStopRecord: () -> Unit
) {
    HoldToTalkRow(
        row = HoldToTalkRowUi(
            waveform = waveform,
            isRecording = isRecording,
            isBusy = isSubmitting,
            micGranted = micGranted,
            onRequestPermission = onRequestPermission,
            onStart = onStartRecord,
            onStop = onStopRecord,
            // busy 特意留空: 在途信号换成带转圈的 [GradingIndicator], 同一屏不说两遍。
            labels = HoldToTalkCopy(idle = "按住说话 / 或打字作答", busy = "")
        )
    )
}

private val DOT_SIZE = 30.dp
private val SPINNER_SIZE = 20.dp
