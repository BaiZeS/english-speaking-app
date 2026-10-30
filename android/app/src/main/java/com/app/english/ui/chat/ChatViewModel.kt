package com.app.english.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.ChatRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.ChatBubbleKind
import com.app.english.domain.model.ChatMessage
import com.app.english.domain.model.SceneRole
import com.app.english.ui.chat.TranslationPlan.LocalToggle
import com.app.english.ui.chat.TranslationPlan.Remote
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

data class ChatUiState(
    val threadId: String = "",
    /** 场景角色表: 气泡上的 `role_id` 要靠它翻成头像与昵称。 */
    val roles: List<SceneRole> = emptyList(),
    val messages: List<ChatMessage> = emptyList(),
    val loading: Boolean = true,
    val submitting: Boolean = false,
    val recording: Boolean = false,
    val micGranted: Boolean = false,
    /** 已经展开中文的气泡 id (界面自己的展示态, 不进 DTO 契约)。 */
    val expanded: Set<String> = emptySet(),
    val turnError: String? = null,
    val translateBusyId: String? = null,
    val translateError: String? = null,
    /** 长按翻译出来的临时结果: 气泡 id -> 译文。 */
    val translations: Map<String, String> = emptyMap()
)

/**
 * 一个场景的群聊。
 *
 * 三件事是这里的硬契约, 都有测试或注释支撑:
 *
 * 1. **失败不许吞气泡**。提交失败时用户刚发出去那颗要留在屏幕上 (v2.3.0 的 `87a64d2`
 *    修过同一件事), 后端 503 时整轮不落库, 所以本地也不许假装它成功了。
 * 2. **评分是回填的**。请求只把评分卡落成 pending, 界面靠轮询 [ChatRepository.getThread]
 *    整份重读把它翻成 ready; `failed` 保持静默但**不停轮询** (过水位还能翻身)。
 * 3. **没有语言开关**。语音一律走后端 `zh_cn` 中英混读听写, 学员说中文还是英文由服务端
 *    从转写文本判 —— 界面上任何"先选语言"的控件都是把一个系统能自己做的事推给用户。
 */
@HiltViewModel
class ChatViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val englishRepository: EnglishRepository,
    private val chatRecorder: ChatRecorder,
    private val playback: ChatPlayback
) : ViewModel() {

    private val _state = MutableStateFlow(ChatUiState())
    val state: StateFlow<ChatUiState> = _state.asStateFlow()

    /** 录音脉冲与"正在录"的真相都在 [ChatRecorder]; VM 只把它转给界面。 */
    val recordingLevel: StateFlow<Float> get() = chatRecorder.level

    /** 播放态 (哪颗在响 + 失败原因) 由 [ChatPlayback] 持有, VM 只转发。 */
    val playingId: StateFlow<String?> get() = playback.playingId
    val playbackError: StateFlow<String?> get() = playback.error

    private var polling: Job? = null

    /** 本机录音 `文件名 -> file:// URI`; 服务端只回显文件名, 路径只有本机知道。 */
    private var sceneKey: String = ""
    private var open = false

    fun open(sceneKey: String, micGranted: Boolean) {
        if (open) return
        open = true
        this.sceneKey = sceneKey
        _state.update { it.copy(micGranted = micGranted) }
        viewModelScope.launch {
            val voices = runCatching {
                englishRepository.listDialogueScenes()
                    .firstOrNull { it.id == sceneKey }
                    ?.roles
                    ?.associate { it.id to it.voice }
            }.getOrNull().orEmpty()
            playback.setVoices(voices)
            val roles = runCatching {
                englishRepository.listDialogueScenes().firstOrNull { it.id == sceneKey }?.roles
            }.getOrNull().orEmpty()
            _state.update { it.copy(roles = roles) }
            try {
                val thread = chatRepository.openThread(sceneKey)
                _state.update {
                    it.copy(threadId = thread.id, messages = thread.messages, loading = false)
                }
                if (anyGradePending(thread.messages)) startGradingPolling()
            } catch (e: Exception) {
                _state.update { it.copy(loading = false, turnError = "开不了这个场景: ${e.message}") }
            }
        }
    }

    fun startRecording() {
        viewModelScope.launch {
            _state.update { it.copy(recording = true, turnError = null) }
            runCatching { chatRecorder.start() }.onFailure { error ->
                // error 必须显式命名: 内层 update 的 lambda 也叫 it, 直接写 it.message
                // 拿到的是 UI state 而不是异常。
                _state.update { it.copy(recording = false, turnError = "录音起不来: ${error.message}") }
            }
        }
    }

    /** 结束录音并送出。失败时**保留**用户那句话的气泡 (见类注释的三条硬契约)。 */
    fun stopAndSend() {
        if (!_state.value.recording) return
        _state.update { it.copy(recording = false) }
        viewModelScope.launch {
            val take = runCatching { chatRecorder.finish() }.getOrNull()
            if (take == null || take.base64.isEmpty()) {
                _state.update { it.copy(turnError = "没录到声音, 再试一次") }
                return@launch
            }
            val optimisticId = "pending_" + System.currentTimeMillis()
            _state.update { current ->
                current.copy(
                    submitting = true,
                    turnError = null,
                    // 先把"我说了话"这颗乐观地摆上屏: 后端 503 时这一轮不落库, 但用户得
                    // 看见自己刚说过什么, 否则整屏像没反应 (v2.3.0 的真机反馈)。
                    messages = current.messages + ChatMessage(
                        id = optimisticId,
                        kind = ChatBubbleKind.USER,
                        localRecording = take.fileName,
                        audioUrl = take.localUri.takeIf { it.isNotBlank() }
                    )
                )
            }
            try {
                val result = chatRepository.submitTurn(
                    threadId = _state.value.threadId,
                    audioBase64 = take.base64,
                    recordingRef = take.fileName
                )
                _state.update { current ->
                    // 乐观那颗换成服务端真落库的那颗 (带 id、听写文本与音频)。
                    val settled = current.messages.filterNot { it.id == optimisticId }
                    current.copy(
                        submitting = false,
                        messages = mergeAppended(settled, result.appended)
                    )
                }
                startGradingPolling()
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        submitting = false,
                        turnError =
                        "这一轮没送出去: " + (e.message ?: e.javaClass.simpleName)
                    )
                }
            }
        }
    }

    fun sendText(text: String) {
        val trimmed = text.trim()
        if (trimmed.isEmpty() || _state.value.submitting) return
        viewModelScope.launch {
            _state.update { it.copy(submitting = true, turnError = null) }
            try {
                val result = chatRepository.submitTurn(_state.value.threadId, text = trimmed)
                _state.update {
                    it.copy(
                        submitting = false,
                        messages = mergeAppended(it.messages, result.appended)
                    )
                }
                startGradingPolling()
            } catch (e: Exception) {
                _state.update {
                    it.copy(
                        submitting = false,
                        turnError = "这一轮没送出去: ${e.message}",
                        messages = it.messages + ChatMessage(
                            id = "local_${System.currentTimeMillis()}",
                            kind = com.app.english.domain.model.ChatBubbleKind.USER,
                            text = trimmed
                        )
                    )
                }
            }
        }
    }

    /** 点语音条: 播音频, 同时展开文字。再点一次收起并停播。 */
    fun onBubbleTap(message: ChatMessage) {
        val showing = _state.value.expanded.contains(message.id)
        when {
            message.kind == com.app.english.domain.model.ChatBubbleKind.LINE && !showing -> {
                setShowingCn(message.id, true)
                playBubble(message)
            }
            showing -> {
                setShowingCn(message.id, false)
                playback.stop()
            }
            else -> {
                setShowingCn(message.id, true)
                playBubble(message)
            }
        }
    }

    private fun playBubble(message: ChatMessage) {
        playback.play(
            message = message,
            localUri = localRecordingPath(message, chatRecorder.taken),
            scope = viewModelScope,
            onFallbackAudio = {
                runCatching {
                    englishRepository.getTtsAudio(message.text, playback.voiceFor(message.roleId))
                }.getOrNull()
            }
        )
    }

    private fun setShowingCn(id: String, show: Boolean) {
        _state.update { it.copy(expanded = if (show) it.expanded + id else it.expanded - id) }
    }

    /**
     * 长按气泡 = 翻译。
     *
     * 有现成双语就**本地切** (台词与建议句都成对返回过, 再问一次 LLM 是把已有的东西
     * 重算一遍, 还让学员多等 1~3 秒); 只有没对照的那句才真调 `/translate`。
     * 翻不出来给一句可读中文 —— 绝不把原文当译文显示, 学员会照着念。
     */
    fun onBubbleLongPress(message: ChatMessage) {
        val plan = translationPlan(message, showingCn = _state.value.expanded.contains(message.id))
        when (plan) {
            is TranslationPlan.LocalToggle -> setShowingCn(message.id, plan.targetLang == LANG_ZH)
            is TranslationPlan.Remote -> {
                if (_state.value.translateBusyId != null) return
                viewModelScope.launch {
                    _state.update { it.copy(translateBusyId = message.id, translateError = null) }
                    try {
                        val translated = englishRepository.translate(plan.text, plan.targetLang)
                        _state.update {
                            it.copy(
                                translateBusyId = null,
                                translations = it.translations + (message.id to translated)
                            )
                        }
                    } catch (e: Exception) {
                        _state.update {
                            it.copy(translateBusyId = null, translateError = "翻译失败, 稍后再试")
                        }
                    }
                }
            }
            TranslationPlan.Nothing -> Unit
        }
    }

    /**
     * 评分回填轮询。判据与旧的实战页判分轮询同源 (见 [GradingPollCadence]):
     * pending 才轮、失败不中断、连续失败到上限就停, 别把手机变成对服务器的拒绝服务。
     */
    private fun startGradingPolling() {
        polling?.cancel()
        polling = viewModelScope.launch {
            var failures = 0
            var waitMillis = GradingPollCadence.FAST_MILLIS
            while (anyGradePending(_state.value.messages) &&
                failures < GradingPollCadence.MAX_FAILURES
            ) {
                delay(waitMillis)
                if (!anyGradePending(_state.value.messages)) {
                    waitMillis = GradingPollCadence.FAST_MILLIS
                }
                val snapshot = runCatching { chatRepository.getThread(_state.value.threadId) }
                    .getOrNull()
                if (snapshot == null) {
                    failures++
                    continue
                }
                failures = 0
                _state.update { it.copy(messages = mergeSnapshot(it.messages, snapshot.messages)) }
                waitMillis = (waitMillis * 2).coerceAtMost(GradingPollCadence.MAX_MILLIS)
            }
        }
    }

    override fun onCleared() {
        polling?.cancel()
        playback.release()
        super.onCleared()
    }
}
