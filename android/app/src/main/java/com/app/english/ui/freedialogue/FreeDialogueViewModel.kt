package com.app.english.ui.freedialogue

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import com.app.english.audio.RecordingStore
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.DialogueMessageDto
import com.app.english.data.remote.sessionMessage
import com.app.english.data.repository.BooksRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.GenerateRepository
import com.app.english.data.repository.HistoryRepository
import com.app.english.data.repository.MistakeWordRepository
import com.app.english.domain.model.DialogueLine
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.DialogueSession
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.navigation.Route
import com.app.english.ui.scenes.GeneratePollingPolicy
import com.app.english.ui.score.LineScoreResult
import com.app.english.ui.score.ScoreSession
import com.app.english.ui.score.ScoreSessionHolder
import dagger.hilt.android.lifecycle.HiltViewModel
import java.io.File
import javax.inject.Inject
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * 聊天气泡模型。
 *
 * [text] 存**协议值** (用户回合 = 识别原文, 识别不到则为空串), 与发给
 * /dialogue/turn 的 history 逐字一致 —— 中文占位提示只发生在渲染层
 * ([FreeDialogueScreen] 按 [hasTranscript] 兜底显示), 不再回流给模型 (P8·2d)。
 */
data class FreeDialogueMessage(
    val role: String,
    val text: String,
    val isUser: Boolean,
    /** false = 用户回合没有识别到任何 transcript (text 为空)。 */
    val hasTranscript: Boolean = true,
    /**
     * D4 双语: 这条气泡的中文 (用户回合 = `learner_cn`, AI 回合 = `reply_cn`)。
     * null/空串 = 那一行不渲染 —— 后端缺字段不补给机翻。
     */
    val translation: String? = null,
    /**
     * 这条用户气泡产生时, 参考回答卡上**正在显示**的那句英文 (§A4/A5)。
     *
     * 只有客户端知道"给过学员哪几句话": 自由对话没有会话表, `suggestedReply` 每轮被
     * 覆盖, 而服务端的防复写需要一个已展示清单 —— [shownSuggestions] 就是把它从消息列表
     * 里还原出来的唯一来源。
     */
    val shownSuggestion: String = ""
)

data class FreeDialogueScore(val suggestedReply: String, val result: ScoreResult)

data class FreeDialogueUiState(
    val isLoading: Boolean = true,
    val isLoadingScenes: Boolean = false,
    val scenes: List<DialogueScene> = emptyList(),
    val selectedSceneId: String = "",
    val sceneId: String = "",
    val title: String = "自由对话",
    val messages: List<FreeDialogueMessage> = emptyList(),
    val suggestedReply: String = "",
    /** D4: 参考回答那句的中文 (要求学员开口的句子默认双语); 空 = 不渲染那一行。 */
    val suggestedReplyCn: String = "",
    /** 「+ 自定义场景」输入弹层开着 (§3 C3)。 */
    val isSceneDialogOpen: Boolean = false,
    /** 场景骨架作业在途 (弹层里显示进度并禁用提交)。 */
    val isCreatingScene: Boolean = false,
    /** 自定义场景失败时的中文文案; 弹层里就地显示, **不**关掉弹层假装成功。 */
    val customSceneError: String? = null,
    val isPlayingReference: Boolean = false,
    val isRecording: Boolean = false,
    val isSubmitting: Boolean = false,
    /**
     * 点按面诚实计时的起点(墙钟 ms)。**只在 [isRecording] 期间有意义** ——
     * [com.app.english.ui.components.TapToTalkRow] 用 isRecording 门控它。
     */
    val recordingStartedAtMs: Long? = null,
    /** 传给 `AudioRecorder.start` 的上限; 决定计时器要不要预告自动发送。 */
    val takeCapMs: Long? = null,
    val currentScore: ScoreResult? = null,
    val scores: List<FreeDialogueScore> = emptyList(),
    val error: String? = null,
    val finished: Boolean = false
)

@HiltViewModel
class FreeDialogueViewModel @Inject constructor(
    private val repository: EnglishRepository,
    private val booksRepository: BooksRepository,
    private val generateRepository: GenerateRepository,
    private val historyRepository: HistoryRepository,
    private val mistakeWordRepository: MistakeWordRepository,
    private val audioRecorder: AudioRecorder,
    private val audioPlayer: AudioPlayer,
    private val audioEncoder: AudioEncoder,
    private val recordingStore: RecordingStore,
    private val settingsStore: SettingsStore,
    private val scoreSessionHolder: ScoreSessionHolder,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    private val lessonId: Int = requireNotNull(
        savedStateHandle.get<Int>(Route.FreeDialogue.ARG_LESSON_ID)
    ) { "lessonId argument required" }
    private val book: String =
        savedStateHandle.get<String>(Route.FreeDialogue.ARG_BOOK) ?: "nce1"

    private val _state = MutableStateFlow(FreeDialogueUiState())
    val state: StateFlow<FreeDialogueUiState> = _state.asStateFlow()

    /**
     * 实时声量脉冲条的电平源(计划 P2 决策 4 点名的缺口之一: 这一页**过去完全没有
     * 电平管线**)。直接转发录音器的 [AudioRecorder.levelFlow] —— 平滑 VU 包络就是
     * 脉冲条的驱动, UI 层不再造第二套平滑; 也不复制进 [FreeDialogueUiState], 那是
     * 25 Hz 的整屏重组, 由叶子组合项自己 collect。电平清零时机由录音器的
     * finalizeTake/cancel/start 独家决定; "定格"观感是 UI 端 RecordingPulseMeter
     * 捕获峰值的职责。
     */
    val micLevel: StateFlow<Float> get() = audioRecorder.levelFlow

    init {
        // 同 PlayerViewModel: 这一局的评分面从零开始, 上一局的残档不能跨局复用(E5)。
        scoreSessionHolder.clear()
        loadScenes()
    }

    fun selectScene(sceneId: String) {
        if (sceneId == _state.value.selectedSceneId) return
        settingsStore.setSelectedSceneId(sceneId)
        generate(sceneId)
    }

    // ====== 自定义场景 (§3 C2/C3b) ======

    fun openSceneDialog() = _state.update {
        // 每次打开都清掉上一次的失败文案: 留着的红字会被读成"这一次也失败了"。
        it.copy(isSceneDialogOpen = true, customSceneError = null)
    }

    fun dismissSceneDialog() {
        if (_state.value.isCreatingScene) return
        _state.update { it.copy(isSceneDialogOpen = false, customSceneError = null) }
    }

    /**
     * 描一个场景 -> 202 + 轮询 -> ready 后**重新拉一次目录**并切过去 (§3 C3)。
     *
     * 轮询节奏、退避与超时水位一律取现成的 [GeneratePollingPolicy] (同一个 job 表、同一个
     * `GET /scenes/jobs/{id}`), 这里不另立一套; 失败与超时都**如实**显示, 不假装成功 ——
     * 目录里没有这一行而界面说"建好了", 学员下一轮就会撞 404。
     */
    fun createCustomScene(brief: String) {
        val trimmed = brief.trim()
        if (trimmed.length < CUSTOM_SCENE_MIN_CHARS || _state.value.isCreatingScene) return
        viewModelScope.launch {
            _state.update { it.copy(isCreatingScene = true, customSceneError = null) }
            try {
                val jobId = generateRepository.startCustomScene(trimmed)
                val sceneId = awaitSceneBriefJob(jobId)
                val scenes = booksRepository.listDialogueScenes()
                _state.update {
                    it.copy(
                        scenes = scenes,
                        isCreatingScene = false,
                        isSceneDialogOpen = false,
                        customSceneError = null,
                        selectedSceneId = sceneId
                    )
                }
                settingsStore.setSelectedSceneId(sceneId)
                generate(sceneId)
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        isCreatingScene = false,
                        customSceneError = e.sessionMessage("自定义场景没生成出来, 稍后再试")
                    )
                }
            }
        }
    }

    /** 轮询到终态; 返回 `custom_<row id>`。失败/超时抛异常 (调用方落成弹层里的中文文案)。 */
    private suspend fun awaitSceneBriefJob(jobId: String): String {
        val startedAt = System.currentTimeMillis()
        var polls = 0
        while (true) {
            // 单次轮询失败按网络抖动放过 (与 GenerateCourseViewModel 同纪律)。
            val job = try {
                generateRepository.pollJob(jobId)
            } catch (e: Exception) {
                Timber.w(e, "scene brief poll failed | job=%s", jobId)
                null
            }
            val elapsed = System.currentTimeMillis() - startedAt
            if (job != null && GeneratePollingPolicy.isTerminal(job)) {
                val sceneId = job.sceneId
                if (job.isReady && !sceneId.isNullOrBlank()) return sceneId
                error(job.error ?: "场景生成失败, 稍后再试")
            }
            if (GeneratePollingPolicy.isTimedOut(elapsed)) {
                error("场景生成超时了 (任务仍在服务端跑), 稍后回来再看看")
            }
            delay(GeneratePollingPolicy.nextDelayMillis(polls))
            polls++
        }
    }

    private fun loadScenes() {
        viewModelScope.launch {
            _state.update { it.copy(isLoadingScenes = true) }
            val scenes = try {
                booksRepository.listDialogueScenes()
            } catch (e: Exception) {
                Timber.w(e, "Failed to load dialogue scenes")
                emptyList()
            }
            val storedSceneId = settingsStore.getSelectedSceneId()
            val initial = storedSceneId?.takeIf { id -> scenes.any { it.id == id } }
                ?: scenes.firstOrNull()?.id
                ?: FALLBACK_SCENE
            if (initial != storedSceneId) {
                settingsStore.setSelectedSceneId(initial)
            }
            _state.update {
                it.copy(
                    scenes = scenes,
                    selectedSceneId = initial ?: "",
                    isLoadingScenes = false
                )
            }
            generate(initial ?: FALLBACK_SCENE)
        }
    }

    fun generate() {
        val scene = _state.value.selectedSceneId.ifBlank { FALLBACK_SCENE }
        generate(scene)
    }

    private fun generate(sceneId: String) {
        viewModelScope.launch {
            _state.update { it.copy(isLoading = true, error = null) }
            _state.value = try {
                val session = repository.generateDialogue(
                    sceneId,
                    "adult",
                    settingsStore.getSelectedModelId()
                )
                session.toUiState()
            } catch (e: Exception) {
                _state.value.copy(isLoading = false, error = e.message ?: "加载自由对话失败")
            }
        }
    }

    private fun DialogueSession.toUiState(): FreeDialogueUiState = FreeDialogueUiState(
        isLoading = false,
        sceneId = sceneId,
        title = title,
        messages = lines.map { it.toUiMessage() },
        suggestedReply = suggestedReply
    )

    private fun DialogueLine.toUiMessage(): FreeDialogueMessage = FreeDialogueMessage(
        role = role,
        text = text,
        isUser = isUser
    )

    fun playLatestAssistant() {
        val message = _state.value.messages.lastOrNull { !it.isUser } ?: return
        if (_state.value.isPlayingReference || _state.value.isRecording) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingReference = true, error = null) }
            try {
                val tts = repository.getTtsAudio(message.text, settingsStore.getVoice())
                if (tts.isStub) {
                    _state.update {
                        it.copy(
                            isPlayingReference = false,
                            error = "AI 语音未配置（后端缺 MIMO_API_KEY），当前无真实语音"
                        )
                    }
                    return@launch
                }
                audioPlayer.play(tts.audioUrl) {
                    _state.update { current -> current.copy(isPlayingReference = false) }
                }
            } catch (e: Exception) {
                _state.update {
                    it.copy(isPlayingReference = false, error = "AI 语音播放失败：${e.message}")
                }
            }
        }
    }

    fun startRecording() {
        if (_state.value.isRecording || _state.value.isSubmitting) return
        _state.update {
            it.copy(
                isRecording = true,
                // 自由对话按 D4 保留点按手势(一轮要说很久), 所以文案必须诚实 + 计时
                // 必须真的在走。上限照抄下面 start() 传的值, 别各写一份。
                recordingStartedAtMs = System.currentTimeMillis(),
                takeCapMs = AudioRecorder.MAX_TAKE_MS,
                currentScore = null,
                error = null
            )
        }
        viewModelScope.launch {
            try {
                audioRecorder.start(
                    maxDurationMs = AudioRecorder.MAX_TAKE_MS,
                    onAutoStop = ::stopAndSubmit
                )
            } catch (e: Exception) {
                _state.update { it.copy(isRecording = false, error = "录音启动失败：${e.message}") }
            }
        }
    }

    fun stopAndSubmit() {
        val current = _state.value
        // P8·2c: 只有「正在录音」才是提交前提。参考回答为空不再拦截 ——
        // 评分 ref 走 scoringRefText() 的兜底 (最后一条 assistant 台词)。
        if (!current.isRecording) return
        viewModelScope.launch {
            // §4-2: 先清再填。等接口的这段时间里, 卡片上不该还挂着上一轮的参考句 ——
            // 那句已经"展示过"了 ([pendingUser.shownSuggestion] 留着它), 但这一轮的新句
            // 还没到。不先清就只是"覆盖", 观感上学员会以为旧的仍有效。
            _state.update {
                it.copy(
                    isRecording = false,
                    isSubmitting = true,
                    suggestedReply = "",
                    suggestedReplyCn = ""
                )
            }
            val file = audioRecorder.stop()
            if (file == null) {
                _state.update { it.copy(isSubmitting = false, error = "录音失败，请重试") }
                return@launch
            }
            val lineId = "free-${current.scores.size + 1}"
            val saved = retainRecording(lineId, file)
            // 学员开口那一刻, 卡片上显示的参考句就是"已展示过的"那一句 (§A4/A5)。
            val pendingUser = FreeDialogueMessage(
                role = "user",
                text = "",
                isUser = true,
                hasTranscript = false,
                shownSuggestion = current.suggestedReply
            )
            try {
                val base64 = withContext(Dispatchers.IO) { audioEncoder.encode(file) }
                if (saved != null) file.delete()
                val refText = scoringRefText(current)
                val result = repository.score(
                    lessonId = lessonId,
                    lineId = lineId,
                    refText = refText,
                    audioBase64 = base64,
                    mode = "free_dialogue"
                )
                collectMistakeWords(lineId, result)
                val history = turnHistory(current.messages + pendingUser)
                val next = repository.dialogueTurn(
                    current.sceneId,
                    history,
                    base64,
                    settingsStore.getSelectedModelId(),
                    shownSuggestions(current.messages + pendingUser)
                )
                val recognized = next.recognizedText.orEmpty()
                _state.update {
                    it.copy(
                        isSubmitting = false,
                        currentScore = result,
                        scores = it.scores + FreeDialogueScore(refText, result),
                        messages = it.messages + pendingUser.copy(
                            text = recognized,
                            hasTranscript = recognized.isNotBlank(),
                            translation = next.learnerCn
                        ) + FreeDialogueMessage(
                            role = "assistant",
                            text = next.replyText,
                            isUser = false,
                            translation = next.replyCn
                        ),
                        suggestedReply = next.suggestedReply,
                        suggestedReplyCn = next.suggestionCn
                    )
                }
            } catch (e: Exception) {
                // §4-6 报错保气泡: 一次 503 (TURN_GENERATION_UNAVAILABLE) 以前会把整轮
                // 用户气泡一起丢掉, 而自由对话**没有服务器记录可以恢复** —— 学员连自己说过
                // 什么都看不到。这一轮的气泡先落地再报错; 转写文本没拿到就是诚实的空
                // (渲染层显示"（这句没有识别到文字）"), 不编造内容。
                Timber.w(e, "free dialogue turn failed")
                _state.update {
                    it.copy(
                        isSubmitting = false,
                        messages = it.messages + pendingUser,
                        error = e.sessionMessage("这一轮没有成功, 请重试")
                    )
                }
            }
        }
    }

    /**
     * Persists the raw take as a WAV via [RecordingStore] for later replay.
     * Retention failure never blocks scoring; returns null in that case.
     */
    private suspend fun retainRecording(lineId: String, file: File): File? = try {
        withContext(Dispatchers.IO) {
            recordingStore.saveRecording(book, lessonId, lineId, file)
        }
    } catch (e: Exception) {
        Timber.w(e, "Failed to retain recording")
        null
    }

    /** Feeds weak words from a successful score into the mistake-word ledger. */
    private suspend fun collectMistakeWords(lineId: String, result: ScoreResult) {
        try {
            mistakeWordRepository.collectFromResult(book, lessonId, lineId, result)
        } catch (e: Exception) {
            Timber.w(e, "Failed to collect mistake words")
        }
    }

    fun finish() {
        val current = _state.value
        if (current.scores.isEmpty()) {
            _state.update { it.copy(error = "至少完成一轮回答后再结束练习") }
            return
        }
        val results = current.scores.map { it.result }
        val session = ScoreSession(
            lessonTitle = current.title,
            roleName = "AI 自由对话",
            totalScore = results.map { it.total }.average(),
            pronunciation = results.map { it.pronunciation }.average(),
            fluency = results.map { it.fluency }.average(),
            completeness = results.map { it.completeness }.average(),
            suggestion = results.mapNotNull { it.suggestion }.lastOrNull(),
            source = if (results.any { it.isStub }) "stub" else "xunfei",
            lineCount = current.scores.size,
            lineResults = current.scores.mapIndexed { index, scored ->
                LineScoreResult(
                    lineId = "free-${index + 1}",
                    text = scored.suggestedReply,
                    total = scored.result.total,
                    wordScores = scored.result.wordDetails
                )
            }
        )
        scoreSessionHolder.session = session
        viewModelScope.launch {
            try {
                historyRepository.write(
                    book = book,
                    lessonId = lessonId,
                    lineId = "free-session",
                    audioPath = "free_session_${System.currentTimeMillis()}",
                    scoreTotal = session.totalScore,
                    scorePronunciation = session.pronunciation,
                    scoreFluency = session.fluency,
                    scoreCompleteness = session.completeness
                )
            } catch (e: Exception) {
                Timber.e(e, "Failed to write free dialogue history")
            }
            _state.update { it.copy(finished = true) }
        }
    }

    fun dismissError() = _state.update { it.copy(error = null) }

    /** 生命周期兜底: ON_STOP 时停+提交(宁发不丢)。 */
    fun stopRecordingIfActive() {
        if (_state.value.isRecording) stopAndSubmit()
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
        if (_state.value.isRecording) audioRecorder.cancel()
    }

    private companion object {
        // Used when /dialogue/scenes returns an empty list (offline / older backend).
        const val FALLBACK_SCENE = "daily_conversation"
    }
}

/**
 * P8·2c: 本轮评分的参考句。suggestedReply 有值就用它; 为空 (模型没给建议 /
 * 生成回包缺字段) 时兜底最后一条 assistant 台词 —— 用户照样可以录音提交,
 * 不再被空建议卡死。两者皆空时返回空串, 由 /score 422 诚实报错。
 */
internal fun scoringRefText(state: FreeDialogueUiState): String =
    state.suggestedReply.ifBlank { state.messages.lastOrNull { !it.isUser }?.text.orEmpty() }

/**
 * P8·2d: /dialogue/turn 的历史构造。用户回合只会带**识别原文或空串**
 * (text 即协议值, 见 [FreeDialogueMessage] 注释), UI 的中文占位提示永不
 * 回流进模型上下文 —— 服务端 P3 起按结构 (末尾 user 回合) 判断, 老包的
 * 「（本轮自由回答）」占位由后端兼容层处理, 新客户端不再生产任何中文哨兵。
 */
internal fun turnHistory(messages: List<FreeDialogueMessage>): List<DialogueMessageDto> =
    messages.map {
        DialogueMessageDto(role = if (it.isUser) "user" else "assistant", text = it.text)
    }

/**
 * §A4/A5: 回给 `/dialogue/turn` 的**已展示参考句**清单 (≤ [SHOWN_SUGGESTIONS_LIMIT])。
 *
 * 服务端有状态的那一半 (实战轮) 从 `mission.turns` 拿; 自由对话没有会话表, 而
 * `suggestedReply` 每轮被覆盖 —— 给过学员哪几句只有客户端知道, 所以由消息列表还原:
 * 每条用户气泡记着它产生时卡片上的那句 ([FreeDialogueMessage.shownSuggestion]), 取最近
 * 去重后的 8 句。去重是必要的: 同一句连着展示两轮, 报两遍只会白占 prompt 预算。
 *
 * 空串/纯空白不参与 (那是"当时没有参考回答", 不是一句已展示的句子)。
 */
internal fun shownSuggestions(messages: List<FreeDialogueMessage>): List<String> =
    messages.mapNotNull { it.shownSuggestion.trim().takeIf(String::isNotEmpty) }
        .distinct()
        .takeLast(SHOWN_SUGGESTIONS_LIMIT)

/** 服务端 `scene_brief` 的长度门下限 (4..200), 客户端先挡一次, 免得白等一轮 422。 */
internal const val CUSTOM_SCENE_MIN_CHARS = 4

/** 长度门上限: 与后端 `Field(max_length=200)` 同一个数 (再长 prompt 也吃不消)。 */
internal const val CUSTOM_SCENE_MAX_CHARS = 200

/** 上面那张清单的上限 —— 与服务端 `shown_suggestions` 的截断口径一致。 */
internal const val SHOWN_SUGGESTIONS_LIMIT = 8
