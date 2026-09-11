package com.app.english.ui.scenes

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.audio.AudioPlayer
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.sessionMessage
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.SessionRepository
import com.app.english.domain.model.ReviewReportData
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.domain.model.SessionSnapshot
import com.app.english.ui.navigation.Route
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch
import timber.log.Timber

data class ReviewUiState(
    val isLoading: Boolean = true,
    val report: ReviewReportData? = null,
    val course: SceneCourseDetail? = null,
    /** 总评文案的作业状态(§P6); null = 未收工, 或这份快照还没这个键(旧数据/字段缺席)。 */
    val reviewStatus: String? = null,
    /** 本轮等待已经烧掉的毫秒数, 只喂 [ReviewPollingPolicy.stageText] 那句措辞。 */
    val elapsedMillis: Long = 0L,
    /** 轮询循环在跑(未终态、未超时、未放弃) —— 第三态的那盏灯。 */
    val isPolling: Boolean = false,
    /**
     * 等待被**主动放弃**(超时或连续网络失败), 而最后一次读到的状态仍是 `generating`。
     * 与 [isPolling] 分开存, 是因为"循环没在跑"有两种含义 —— 等到了终态 vs 没等到;
     * 页面只在后一种情况下放那颗「再问一次」的键, 前一种不该多一个按了没用的出口。
     */
    val gaveUpWaitingForCopy: Boolean = false,
    val error: String? = null,
    val isPlayingLine: Boolean = false
) {
    /**
     * 页面渲染态。决策本身是纯函数, 见 [ReviewStateMachine.phaseOf] —— 三态里"数值已在、
     * 文案在写"这一态最容易被写错成整页 spinner, 所以把判断挪出 Composable 单独测。
     */
    val phase: ReviewPhase
        get() = ReviewStateMachine.phaseOf(
            ReviewPhaseInput(
                status = reviewStatus,
                hasReport = report != null,
                firstLoadInFlight = isLoading,
                pollInFlight = isPolling,
                gaveUpWhileGenerating = gaveUpWaitingForCopy
            )
        )
}

/**
 * 复盘报告页(计划 §6.4 ReviewScreen): 总分圆环 + 4 维条 + ability_delta + checklist +
 * 原话对照 + new_tokens + 参考剧本可播。数据来自 `GET /sessions/{id}` 的 `review` 分区。
 *
 * §P6 之后本页**不再假设一次 GET 就能拿到终稿**: 收工是 202, 数值骨架当场落库, AI 文案
 * 由服务端后台作业补。所以 [load] 拉一次之后按 [ReviewPollingPolicy] 的节奏继续 GET 同一
 * 份快照, 直到 `review_status` 落到终态。**没有新的轮询端点**, "重试"也不是另一个调用 ——
 * 就是再 GET 一次, 服务端会顺手把卡住的作业就地重派。
 */
@HiltViewModel
class ReviewViewModel @Inject constructor(
    private val sessionRepository: SessionRepository,
    private val englishRepository: EnglishRepository,
    private val settingsStore: SettingsStore,
    private val audioPlayer: AudioPlayer,
    savedStateHandle: SavedStateHandle
) : ViewModel() {
    val sessionId: String =
        savedStateHandle.get<String>(Route.SceneReview.ARG_SESSION_ID).orEmpty()

    private val _state = MutableStateFlow(ReviewUiState())
    val state: StateFlow<ReviewUiState> = _state.asStateFlow()

    /** 同一时刻只允许一个轮询循环: 重试必须点掉上一个, 否则两条循环会在同一份快照上互相覆盖。 */
    private var pollingJob: Job? = null

    init {
        load()
    }

    /** 拉一次快照, 并在文案还没写完时继续轮询。也是所有「重试」按钮的唯一落点。 */
    fun load() {
        pollingJob?.cancel()
        pollingJob = viewModelScope.launch { pollUntilSettled() }
    }

    private suspend fun pollUntilSettled() {
        val startedAt = System.currentTimeMillis()
        var polls = 0
        var failures = 0
        var lastFailureText: String? = null
        var hasSnapshot = false
        // 用**最近一次读到**的状态, 而不是这一轮的: 这次 GET 挂了并不意味服务端把
        // `generating` 翻了回去。脏值同理原样透传 —— 它不许当 `generating` 用。
        var lastKnownStatus: String? = null
        _state.update { it.copy(error = null, gaveUpWaitingForCopy = false, elapsedMillis = 0L) }
        while (true) {
            val snapshot = try {
                sessionRepository.get(sessionId)
            } catch (e: Exception) {
                // 单次失败按网络抖动放过(容忍额度在 ReviewStateMachine)。绝不清页面:
                // 数值早已落库, 因为一次丢包就把学员已到手的成绩抹成红字是本末倒置。
                failures++
                lastFailureText = e.sessionMessage("加载复盘失败")
                Timber.w(e, "review snapshot fetch failed | session=%s poll=%d", sessionId, polls)
                null
            }
            val elapsed = System.currentTimeMillis() - startedAt
            if (snapshot != null) {
                failures = 0
                hasSnapshot = true
                lastKnownStatus = snapshot.reviewStatus
                applySnapshot(snapshot, elapsed)
            }
            when (
                val step = ReviewStateMachine.nextPollStep(
                    pollCount = polls,
                    elapsedMillis = elapsed,
                    status = lastKnownStatus,
                    consecutiveFailures = failures
                )
            ) {
                is ReviewPollStep.Wait -> {
                    _state.update {
                        it.copy(isLoading = !hasSnapshot, isPolling = true, elapsedMillis = elapsed)
                    }
                    delay(step.delayMillis)
                    polls++
                }

                is ReviewPollStep.GaveUp -> {
                    // 放弃等待: 有数值就照常画数值, 欠的只是文案区那颗「再问一次」的键;
                    // 一份快照都没拿到, 才让整页退化成可重试错误态。
                    _state.update {
                        it.copy(
                            isLoading = false,
                            isPolling = false,
                            elapsedMillis = elapsed,
                            gaveUpWaitingForCopy = hasSnapshot,
                            error = if (hasSnapshot) {
                                null
                            } else {
                                giveUpText(
                                    step.reason,
                                    lastFailureText
                                )
                            }
                        )
                    }
                    return
                }

                ReviewPollStep.Stop -> {
                    _state.update {
                        it.copy(
                            isLoading = !hasSnapshot,
                            isPolling = false,
                            elapsedMillis = elapsed,
                            error = if (hasSnapshot) null else lastFailureText ?: it.error
                        )
                    }
                    return
                }
            }
        }
    }

    private fun applySnapshot(snapshot: SessionSnapshot, elapsed: Long) {
        _state.update {
            it.copy(
                isLoading = false,
                // 骨架与文案是**同一份** review, 但轮询中途万一读到半份(理论不该发生),
                // 留着上一轮的比擦掉强。
                report = snapshot.review ?: it.report,
                course = snapshot.course ?: it.course,
                reviewStatus = snapshot.reviewStatus,
                elapsedMillis = elapsed,
                // 数值到手即清错误: 上一次轮询的丢包不该继续留在页面上。
                error = null
            )
        }
    }

    private fun giveUpText(reason: ReviewPollStep.Reason, failureText: String?): String =
        when (reason) {
            ReviewPollStep.Reason.NETWORK -> failureText ?: "连不上服务器, 请检查网络后重试"
            ReviewPollStep.Reason.TIMEOUT ->
                "等 AI 总评等得太久了 (它可能仍在服务端写), 点这里再问一次"
        }

    /** 参考剧本台词播放(stub URL 照常播, 失败静默)。 */
    fun playLine(text: String) {
        if (_state.value.isPlayingLine || text.isBlank()) return
        viewModelScope.launch {
            _state.update { it.copy(isPlayingLine = true) }
            try {
                val tts = englishRepository.getTtsAudio(text, settingsStore.getVoice())
                audioPlayer.play(tts.audioUrl) {
                    _state.update { s -> s.copy(isPlayingLine = false) }
                }
            } catch (e: Exception) {
                Timber.w(e, "review tts failed")
                _state.update { it.copy(isPlayingLine = false) }
            }
        }
    }

    override fun onCleared() {
        super.onCleared()
        audioPlayer.release()
    }
}
