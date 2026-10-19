package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.backendErrorCode
import com.app.english.data.remote.backendErrorMessage
import com.app.english.data.remote.sessionErrorCodeText
import com.app.english.data.remote.sessionMessage
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.ExpressionRepository
import com.app.english.data.repository.PolishCollectRequest
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.HintData
import com.app.english.domain.model.MissionTurnLog
import com.app.english.domain.model.MissionTurnResult
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.SessionSnapshot
import com.app.english.domain.model.TaskChip
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import retrofit2.HttpException
import timber.log.Timber

/** 聊天列表里的一条气泡。 */
sealed interface MissionBubble {
    val turnIndex: Int

    /**
     * **单调 id**: LazyColumn 的 key 只认它 (见 [MissionBubbleIds])。
     *
     * 为什么不能再用内容当 key: 「失败也落气泡」之后, 语音发送连挂两次会落下两条
     * `User("", hasTranscript=false, 同一个 turnIndex)` —— 逐字节相同。旧 key
     * (`class-turnIndex-hashCode`) 于是重复, LazyColumn 当场抛 IllegalArgumentException
     * 崩溃。id 还顺手治好另一件事: 内容一变 key 就变, 这一项的组合状态 (例如「译」的展开
     * 态) 会被丢掉重算; 有了稳定 id, 刷新判分结果不再把展开态收回去。
     */
    val id: Long

    data class Ai(
        val text: String,
        override val turnIndex: Int,
        val translation: String? = null,
        override val id: Long = 0L
    ) : MissionBubble

    /**
     * 用户台词; 无转写时诚实显示占位(不再编造字面量)。
     *
     * [speech] 是这一轮的发音读数(维度分/语速/没读准的词)。语音轮才有, 纯文本轮为
     * null —— 它现在**也**能从恢复快照里拿到 (§A3 之后 `mission.turns[].sub_scores`
     * 已经落库), 所以重进实战页与判分回填都不会再把它弄丢。
     *
     * [gradingPending] = §A3 的第三态: 台词已经出来了, 润色与语法/词汇分还在后台作业里,
     * 这一行显示「评分生成中…」而不是空着。`failed` **不是**这一态 (静默缺省, 不弹窗)。
     */
    data class User(
        val text: String,
        val hasTranscript: Boolean,
        val polish: PolishBubble?,
        val speech: SpeechStrip? = null,
        val translation: String? = null,
        val gradingPending: Boolean = false,
        override val turnIndex: Int,
        override val id: Long = 0L
    ) : MissionBubble
}

/**
 * 气泡 id 的**唯一来源**: 一次 ViewModel 会话里单调递增, 跨重进也只需在当前这份列表内
 * 唯一 (key 的唯一性是 LazyColumn 的一次组合范围, 不是全局不变量)。
 *
 * 单独抽成一个类是为了能测 —— 崩溃的成因是"两条内容完全相同的气泡拿到同一个 key",
 * 而那个判据不在 Composable 里, 就在这里。
 */
internal class MissionBubbleIds(private var latest: Long = 0L) {
    fun next(): Long = ++latest
}

/**
 * 409/400 等状态机错误的 Snackbar 文案。
 *
 * 通用码表在 [sessionErrorCodeText](按 code 命中中文 > 后端中文 message > 兜底,
 * 永不出英文)。这里只覆盖**实战页语境下含义不同**的一条: `WRONG_STAGE` 在实战页
 * 意味着"打基础还没走完", 在打基础页则是"按清单顺序来"。
 */
fun missionErrorCodeText(code: String?, backendMessage: String?): String = when (code) {
    "WRONG_STAGE" -> "请先完成打基础步骤"
    else -> sessionErrorCodeText(
        code = code,
        backendMessage = backendMessage,
        fallback = "发送失败, 请重试"
    )
}

/**
 * §A3 判分回填的**合并规则**(纯函数, JVM 可测)。
 *
 * 只动"还在等判分"的那几条用户气泡, 别的原样返回:
 * - 已落定的轮次再合一次没有意义, 而且会把学员正在看的那一屏无谓地重组;
 * - 报错留下的那一轮 (turnIndex 可能与重试成功的轮次相同, `gradingPending` 恒 false)
 *   不该被别人的判分覆盖 —— 它本来就不是一次成功的实战轮。
 *
 * `failed` 的轮次把 [MissionBubble.User.gradingPending] 收掉 = 那一行**静默缺省**:
 * 判分失败的意思是"这一轮没有润色/分数", 不是"这一轮不存在", 更不该弹一个「评分失败」。
 */
internal fun applyGradingToBubbles(
    bubbles: List<MissionBubble>,
    turns: List<MissionTurnLog>
): List<MissionBubble> {
    if (turns.isEmpty()) return bubbles
    val byTurn = turns.associateBy { it.turnIndex }
    return bubbles.map { bubble ->
        val log = if (bubble is MissionBubble.User && bubble.gradingPending) {
            byTurn[bubble.turnIndex]
        } else {
            null
        }
        if (bubble is MissionBubble.User && log != null) {
            val learnerCn = log.learnerCn.ifBlank { bubble.translation.orEmpty() }
            bubble.copy(
                polish = log.polish.toBubbleOrNull(),
                speech = speechStripOf(log.subScores, log.wordDetails, log.speechRateWpm)
                    ?: bubble.speech,
                translation = learnerCn.takeIf(String::isNotBlank),
                gradingPending = GradingPollingPolicy.isPending(log.gradingStatus)
            )
        } else {
            bubble
        }
    }
}

data class MissionUiState(
    val isLoading: Boolean = true,
    val bubbles: List<MissionBubble> = emptyList(),
    val checklist: List<TaskChip> = emptyList(),
    val turnCount: Int = 0,
    val maxTurns: Int = 0,
    val personaCn: String = "",
    val suggestion: String = "",
    /** D4: 「试试这么说」那句的中文 (`suggestion_cn`); 空 = 不渲染那一行。 */
    val suggestionCn: String = "",
    val isSubmitting: Boolean = false,
    val isRecording: Boolean = false,
    val isPlaying: Boolean = false,
    val hint: HintData? = null,
    val hintWarnsScore: Boolean = false,
    val finished: Boolean = false,
    /**
     * 「收工」请求在途(§2.6 E2)。刻意不等于 [isSubmitting](那一位涵盖发一轮/要提示,
     * 用它会把"对话请求还挂着"误判成"不能收工", 学员连弹窗都打不开), 更不等于
     * [finished](那位的语义是"服务端已关闭本场", 超时路径下它一直是 false —— 正是原 bug
     * 让整条退出链路持续可重入的原因)。
     */
    val isFinishing: Boolean = false,
    /**
     * 上一次收工**没成功**时那句中文文案; 非 null 就是"要摆出显式出口"的那一位。
     *
     * 刻意不回写通用的 [error]: 红字埋在气泡流末尾不是一个出口(那正是原来"只能重开弹窗
     * 再猜一次"的形状), 而且会和这一轮真正要说的话混在一起。用一个自己的键, 让"失败"
     * 与"界面该给出口"是同一件事实, 不需要第二个布尔。
     */
    val finishError: String? = null,
    /**
     * 一次性导航请求(one-shot 事件): 到轮次上限被服务端**自动收工**时置起, 界面消费后跳
     * 复盘页。人工「收工」不走这里, 因为弹窗那条路径手上有 `onOpenReview` 回调; 自动收工
     * 发生在发下一轮的协程里, 那里没有任何导航参数 —— 为这一个分支把回调穿进
     * `sendTurn`/`stopRecordingAndSend`/`sendText` 三个入口, 换不到任何清晰。
     */
    val openReviewRequested: Boolean = false,
    /** 一闪而过的提示(新任务达成 reason / 收藏结果)。 */
    val snackbar: String? = null,
    val error: String? = null
) {
    /** HUD「第 n/max 轮 · 已勾 m/k 项」。 */
    val hudText: String
        get() = "第 $turnCount/$maxTurns 轮 · 已勾 ${taskProgressLabel(checklist)} 项"

    /** 有没有什么东西在途(发一轮 / 要提示 / 收工)。重复提交守卫读的就是这一位。 */
    val inFlight: Boolean get() = isSubmitting || isFinishing
}

/**
 * 实战对话页(计划 §6.4 MissionScreen, 聊天软件式): 状态机驱动, 服务端持权威
 * 进度; 润色嵌在用户气泡下, 任务 chips 横滑, 退出需确认并 finish-mission。
 */
@HiltViewModel
class MissionViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val expressionRepository: ExpressionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioRecorder: AudioRecorder,
    private val audioEncoder: AudioEncoder,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sessionId: String =
        savedStateHandle.get<String>(Route.SceneMission.ARG_SESSION_ID).orEmpty()

    private val _state = MutableStateFlow(MissionUiState())
    val state: StateFlow<MissionUiState> = _state.asStateFlow()

    private var snapshot: SessionSnapshot? = null
    private var sceneId: String = ""

    /** §A3 判分回填循环 (同一时刻只允许一个; 重进/连轮都只是"确保它在跑")。 */
    private var gradingPollJob: Job? = null

    /** 气泡 id 源 (LazyColumn 的 key 只认它, 见 [MissionBubbleIds])。 */
    private val bubbleIds = MissionBubbleIds()

    init {
        restore()
    }

    /**
     * 实时声量脉冲条的电平源: 直接转发录音器的 [AudioRecorder.levelFlow]。平滑 VU
     * 包络**就是**脉冲条的驱动 —— "快起慢落"的手感来自包络本身, UI 层不再造第二套
     * 平滑。它**不进** [MissionUiState]: 25 Hz 的整屏重组对聊天页是白扔的帧, 由叶子
     * 组合项自己 collect。电平清零时机仍由 finalizeTake/cancel/start 独家决定;
     * "定格"观感(峰值捕获)是 UI 端 RecordingPulseMeter 的职责, VM 不管电平。
     */
    val micLevel: StateFlow<Float> get() = audioRecorder.levelFlow

    /** 恢复: 打基础没打完就退回; 否则按快照重绘气泡与清单。 */
    fun restore() {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true) }
            try {
                val loaded = sessionRepository.get(sessionId)
                snapshot = loaded
                sceneId = loaded.sceneId
                val mission = loaded.mission
                if (loaded.stage == "briefing" || mission == null) {
                    _state.update {
                        it.copy(isLoading = false, error = BRIEFING_NOT_DONE, finished = true)
                    }
                    return@launch
                }
                val course = loaded.course
                val opening = mission.openingA.ifBlank { course?.mission?.openingA.orEmpty() }
                // D4「不等 LLM 先透」: 开场白的中文库里早有 (`opening_a_cn`), 恢复页面时
                // 一个字节的生成都不用等 —— 这正是 A7' 那段"把库里已有的双语透出来"。
                val openingCn = mission.openingACn.ifBlank { course?.mission?.openingACn.orEmpty() }
                val bubbles = buildList {
                    add(
                        MissionBubble.Ai(
                            text = opening,
                            turnIndex = 0,
                            translation = openingCn,
                            id = bubbleIds.next()
                        )
                    )
                    mission.turns.forEach { turn ->
                        add(
                            MissionBubble.User(
                                text = turn.transcript,
                                hasTranscript = turn.transcript.isNotBlank(),
                                polish = turn.polish.toBubbleOrNull(),
                                speech = speechStripOf(
                                    turn.subScores,
                                    turn.wordDetails,
                                    turn.speechRateWpm
                                ),
                                translation = turn.learnerCn,
                                gradingPending = GradingPollingPolicy.isPending(turn.gradingStatus),
                                turnIndex = turn.turnIndex,
                                id = bubbleIds.next()
                            )
                        )
                        add(
                            MissionBubble.Ai(
                                text = turn.reply,
                                turnIndex = turn.turnIndex,
                                translation = turn.replyCn,
                                id = bubbleIds.next()
                            )
                        )
                    }
                }
                _state.update {
                    it.copy(
                        isLoading = false,
                        bubbles = bubbles,
                        checklist = mission.tasks,
                        turnCount = mission.turnCount,
                        maxTurns = mission.maxTurns,
                        personaCn = course?.mission?.personaCn.orEmpty(),
                        finished = loaded.status != "active",
                        // "收工成功但响应没能回到手机上"之后重进这一页: 服务端早已
                        // `completed`, 而这一场的报告(哪怕只是数值骨架)已经在快照里。
                        // 停在聊天页就是把人困在一个既不能输入、也看不到总评的死界面上 ——
                        // 那正是 §2 问题 5 的原始观感, 所以这里直接把「去复盘」摆出来。
                        openReviewRequested = loaded.status != "active" &&
                            (
                                loaded.review != null ||
                                    loaded.reviewStatus == ReviewPollingPolicy.STATUS_GENERATING
                                )
                    )
                }
                // 重进这一页时判分可能还在作业里: 接着轮 —— 否则"进来早了两秒"就永远
                // 卡在「评分生成中…」上, 而服务端其实早就把润色写好了。
                if (GradingPollingPolicy.isAwaiting(loaded.gradingStatus)) pollGradingUntilSettled()
            } catch (e: Exception) {
                _state.update { it.copy(isLoading = false, error = e.userMessage()) }
            }
        }
    }

    fun updateDraft(text: String) {
        draft = text
    }

    private var draft: String = ""

    fun sendText() {
        val text = draft.trim()
        if (text.isEmpty() || _state.value.inFlight || _state.value.finished) return
        draft = ""
        viewModelScope.launch { sendTurn(text = text, audioB64 = null) }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.inFlight) return
        // 乐观翻位: 按住放手的同一帧就把录音态立起来, 硬件启动挪到 IO 协程里,
        // 主线程不再阻塞 AudioRecord 构造(旧写法既卡手感, 又给了双击过守卫的窗口)。
        _state.update { it.copy(isRecording = true, error = null) }
        viewModelScope.launch {
            try {
                audioRecorder.start(
                    maxDurationMs = AudioRecorder.MAX_TAKE_MS,
                    onAutoStop = ::stopRecordingAndSend
                )
            } catch (e: Exception) {
                _state.update {
                    it.copy(isRecording = false, error = "录音启动失败：${e.message}")
                }
            }
        }
    }

    fun stopRecordingAndSend() {
        if (!_state.value.isRecording) return
        // 只翻录音位: 脉冲条的定格峰值由 RecordingPulseMeter 自己捕获, VM 不管电平。
        _state.update { it.copy(isRecording = false) }
        viewModelScope.launch {
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(error = "录音失败，请重试") }
                return@launch
            }
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                sendTurn(text = null, audioB64 = base64)
            } finally {
                file.delete()
            }
        }
    }

    /** 生命周期兜底: ON_STOP 时走停+发送(宁发不丢)。 */
    fun stopRecordingIfActive() {
        if (_state.value.isRecording) stopRecordingAndSend()
    }

    private suspend fun sendTurn(text: String?, audioB64: String?) {
        _state.update { it.copy(isSubmitting = true, error = null) }
        try {
            val result = sessionRepository.missionTurn(sessionId, text, audioB64)
            consumeTurnResult(result)
        } catch (e: Exception) {
            // §4-6 报错保气泡: 一次 503 (TURN_GENERATION_UNAVAILABLE) 以前会让这一轮的
            // 用户气泡彻底消失, 学员连自己刚说过什么都看不到。打字轮把原话摆回去; 语音轮
            // 的转写没回来 (它在服务端那半丢了), 就诚实地摆一个"没识别到文字"的气泡 ——
            // 宁可留一个说真话的空位, 也不让这一轮在聊天流里蒸发。
            _state.update { current ->
                current.copy(
                    isSubmitting = false,
                    bubbles = current.bubbles + MissionBubble.User(
                        text = text.orEmpty(),
                        hasTranscript = !text.isNullOrBlank(),
                        polish = null,
                        turnIndex = current.turnCount + 1,
                        id = bubbleIds.next()
                    ),
                    error = e.missionMessage()
                )
            }
        }
    }

    private fun consumeTurnResult(result: MissionTurnResult) {
        val turn = result.turn
        val gradingPending = GradingPollingPolicy.isPending(turn.gradingStatus)
        _state.update { current ->
            current.copy(
                isSubmitting = false,
                bubbles = current.bubbles + MissionBubble.User(
                    text = turn.transcript,
                    hasTranscript = turn.transcript.isNotBlank(),
                    polish = turn.polish.toBubbleOrNull(),
                    speech = speechStripOf(turn),
                    translation = turn.learnerCn,
                    gradingPending = gradingPending,
                    turnIndex = turn.turnIndex,
                    id = bubbleIds.next()
                ) + MissionBubble.Ai(
                    text = turn.reply,
                    turnIndex = turn.turnIndex,
                    translation = turn.replyCn,
                    id = bubbleIds.next()
                ),
                checklist = result.checklist,
                turnCount = result.turnCount,
                maxTurns = result.maxTurns,
                suggestion = turn.suggestion,
                suggestionCn = turn.suggestionCn,
                finished = result.finished,
                hint = null,
                hintWarnsScore = false,
                snackbar = result.turn.newlyDone.firstOrNull()?.evidence
            )
        }
        // §A3: 台词到手、判分还在作业里 -> 按现成节奏轮 `GET /sessions/{id}` 回填润色、
        // 逐词染色与清单。`failed` 也继续轮 (水位过后服务端会重派, 它可能翻身成 `ready`),
        // 但界面上那一行**静默缺省** —— 判分失败 = 这一轮没有润色, 不是"这一轮不存在"。
        if (GradingPollingPolicy.isAwaiting(result.gradingStatus)) pollGradingUntilSettled()
        // 到轮次上界的自动收工(§P6 客户端 4): 响应带的是**数值骨架** + `generating`。
        // 三个信号任一成立都算收工, 因为服务端在这一条路径上是同时给它们的, 而其中任何一个
        // 单独出现都已经说明"这一场结束了": 只看 `review != null` 会漏掉"骨架还在路上"的
        // 未来变体, 只看 `finished` 又回到那个把"服务端关掉了"当"我可以跳了"的混用。
        val autoFinished = result.finished || result.review != null || result.reviewStatus != null
        if (autoFinished) {
            _state.update {
                it.copy(
                    finished = true,
                    openReviewRequested = true,
                    snackbar = "回合用完, 已自动收工"
                )
            }
        }
    }

    /** 界面消费掉一次性「去复盘」导航请求(LaunchedEffect 里调一次, 避免重组时重复导航)。 */
    fun consumeReviewRequest() = _state.update { it.copy(openReviewRequested = false) }

    /**
     * §A3 判分回填循环。
     *
     * **不新增端点、不新增轮询机制**: 打的就是 `GET /sessions/{id}` ([restore] 用的同一个
     * 读路径), 节奏取现成的 [ReviewPollingPolicy] (2s 起探、线性退避到 6s 封顶、5 分钟放弃
     * —— 判分实测 5-15s, 这个水位连服务端一次重派周期都盖得住)。服务端在 GET 里顺手把卡住
     * 的判分作业就地重派, 所以 `failed` **也要继续轮** (后端契约点名要求: 它可能翻身成
     * `ready`), 但界面那行静默缺省, 绝不弹「评分失败」。
     *
     * 同一时刻只允许一个循环 (重进/连轮都会想启动它, 两条循环会在同一份快照上互相覆盖)。
     */
    private fun pollGradingUntilSettled() {
        if (gradingPollJob?.isActive == true) return
        gradingPollJob = viewModelScope.launch {
            val startedAt = System.currentTimeMillis()
            var polls = 0
            var failures = 0
            var sawSnapshot = false
            var lastStatus: String? = null
            while (true) {
                val snapshot = try {
                    sessionRepository.get(sessionId)
                } catch (e: Exception) {
                    // 单次丢包按网络抖动放过: 判分晚到几秒不是事故, 把整页变成红字才是。
                    failures++
                    Timber.w(e, "grading poll failed | session=%s poll=%d", sessionId, polls)
                    null
                }
                val elapsed = System.currentTimeMillis() - startedAt
                if (snapshot != null) {
                    failures = 0
                    sawSnapshot = true
                    lastStatus = snapshot.gradingStatus
                    _state.update { current ->
                        current.copy(
                            bubbles = applyGradingToBubbles(
                                current.bubbles,
                                snapshot.mission?.turns.orEmpty()
                            ),
                            // 判分作业会顺手把任务清单往前推 (done 粘滞, 只许变好):
                            // 让学员看到的那几枚勾与刚落的判分是同一份事实。
                            checklist = snapshot.mission?.tasks?.takeIf { it.isNotEmpty() }
                                ?: current.checklist
                        )
                    }
                }
                val keep = GradingPollingPolicy.shouldKeepPolling(
                    status = lastStatus,
                    sawSnapshot = sawSnapshot,
                    consecutiveFailures = failures,
                    elapsedMillis = elapsed
                )
                if (!keep) {
                    // 放弃等待 (超时 / 连续丢包): 把「评分生成中…」收掉 —— 我们不再问了,
                    // 再挂着那行字就是替一个没人盯的作业打保票。`failed` 与放弃都是静默的。
                    clearGradingPending()
                    return@launch
                }
                delay(ReviewPollingPolicy.nextDelayMillis(polls))
                polls++
            }
        }
    }

    /** 不再等待时收掉第三态: 那一行回到"没有润色就不画"的缺省。 */
    private fun clearGradingPending() = _state.update { current ->
        current.copy(bubbles = current.bubbles.map(::withoutGradingPending))
    }

    private fun withoutGradingPending(bubble: MissionBubble): MissionBubble =
        if (bubble is MissionBubble.User && bubble.gradingPending) {
            bubble.copy(gradingPending = false)
        } else {
            bubble
        }

    fun requestHint() {
        if (_state.value.inFlight || _state.value.finished) return
        viewModelScope.launch {
            _state.update { it.copy(isSubmitting = true, error = null) }
            try {
                val hint = sessionRepository.hint(sessionId)
                _state.update {
                    it.copy(isSubmitting = false, hint = hint, hintWarnsScore = true)
                }
            } catch (e: Exception) {
                _state.update { it.copy(isSubmitting = false, error = e.missionMessage()) }
            }
        }
    }

    fun dismissHint() = _state.update { it.copy(hint = null) }

    /** AI 气泡点击播放: 沿用 /tts; stub 音频同样有 URL, 照常播。 */
    fun playAiBubble(text: String) {
        if (_state.value.isPlaying) return
        viewModelScope.launch {
            _state.update { it.copy(isPlaying = true) }
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) { _state.update { s -> s.copy(isPlaying = false) } }
            } catch (e: Exception) {
                Timber.w(e, "mission tts failed")
                _state.update { it.copy(isPlaying = false, snackbar = "语音播放失败") }
            }
        }
    }

    /** 润色气泡 ⭐收藏 -> POST /expressions(重复收藏后端返回既有条目)。 */
    fun collectPolish(polish: PolishSuggestion) {
        viewModelScope.launch {
            try {
                val (created, _) = expressionRepository.collect(
                    PolishCollectRequest(
                        polished = polish.polished,
                        original = polish.original,
                        explanationCn = polish.explanationCn,
                        sourceLabel = "mission",
                        sceneId = sceneId,
                        sessionId = sessionId
                    )
                )
                _state.update {
                    it.copy(snackbar = if (created) "已收进表达库" else "这句话已经在表达库里")
                }
            } catch (e: Exception) {
                // 收藏打不动只是个小挫折, 但也得有中文: 这条以前直出 `e.message`。
                _state.update { it.copy(snackbar = e.sessionMessage("收藏失败, 稍后再试")) }
            }
        }
    }

    fun consumeSnackbar() = _state.update { it.copy(snackbar = null) }

    fun dismissError() = _state.update { it.copy(error = null) }

    /** 收工失败后的「先去看复盘」: 报告在不在由复盘页自己说清, 这里不替它猜。 */
    fun openReviewAfterFailure(onOpenReview: (String) -> Unit) {
        // **不**翻 `finished`: 这一步我们并不知道服务端有没有关掉这一场。报告在不在由
        // 复盘页按快照自己说(`review == null` 时它会给一句诚实的可重试错误态)。
        _state.update { it.copy(finishError = null) }
        onOpenReview(sessionId)
    }

    /** 收掉失败出口(弹窗被 dismiss 时), 不动会话状态。 */
    fun dismissFinishError() = _state.update { it.copy(finishError = null) }

    /**
     * 退出确认后的收工(§P6 客户端 6 + §2.6 E2)。
     *
     * 两道门顺序是刻意的: **在途 -> 什么都不做**(那 4 连 409 的直接对策), 已 finished ->
     * 不重复请求、直接跳。拿到 202 就**立刻**跳复盘页, 不再在这里等 AI 文案: 服务端在
     * commit 202 之前已经把数值/历史行/`status="completed"` 全写完了, 欠的只有那两句总评,
     * 而那部分归复盘页轮询。
     */
    fun finishAndReview(onOpenReview: (String) -> Unit) {
        when (
            MissionFinishGuard.tapOf(
                finished = _state.value.finished,
                inFlight = _state.value.inFlight
            )
        ) {
            FinishTap.IGNORE_IN_FLIGHT -> return
            FinishTap.OPEN_REVIEW -> onOpenReview(sessionId)
            FinishTap.SUBMIT -> Unit
        }
        // 在途位**同步**立起来, 不能等 `launch` 里再翻: 主线程同一帧内的第二次「收工」会
        // 在协程排队之前就跑到这里, 于是守卫看到的是 `isFinishing == false` —— 那正是
        // "点两下发出两个请求"的窗口, 也是 E2 要堵的那一个。
        _state.update { it.copy(isFinishing = true, finishError = null) }
        viewModelScope.launch {
            try {
                val ack = sessionRepository.finishMission(sessionId)
                Timber.i(
                    "mission finish accepted | session=%s review_status=%s",
                    ack.sessionId,
                    ack.reviewStatus
                )
                _state.update { it.copy(isFinishing = false, finished = true) }
                onOpenReview(sessionId)
            } catch (e: Exception) {
                val code = (e as? HttpException)?.backendErrorCode()
                if (MissionFinishGuard.failureMeansAlreadyFinished(code)) {
                    // 已经收工的幂等场景(409 MISSION_FINISHED)照样进复盘。
                    _state.update { it.copy(isFinishing = false, finished = true) }
                    onOpenReview(sessionId)
                } else {
                    // 复位在途位 + 留下**中文**失败文案: 界面上「重试收工」与「先去看复盘」
                    // 两条出口都由它驱动。读超时**不代表**服务端没做完, 所以第二条不是摆设。
                    _state.update {
                        it.copy(isFinishing = false, finishError = e.missionMessage())
                    }
                }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }

    private fun Throwable.missionMessage(): String = when (this) {
        is HttpException -> missionErrorCodeText(backendErrorCode(), backendErrorMessage())
        // 读超时的异常 message 是裸英文 "timeout", 此前被原样渲染成红字; 更要紧的是
        // 超时**不代表服务端没做完** —— 收工的复盘报告往往已经落库, 所以文案引导去
        // 复盘/历史里确认, 而不是让人反复重点「收工」(生产日志里那 4 连 409 即由此来)。
        else -> sessionMessage(fallback = "发送失败, 请重试")
    }

    private companion object {
        private const val BRIEFING_NOT_DONE = "实战还没解锁, 先把打基础清单走完"
    }
}
