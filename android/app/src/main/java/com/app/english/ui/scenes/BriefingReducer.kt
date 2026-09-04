package com.app.english.ui.scenes

import com.app.english.domain.model.BriefingProgress
import com.app.english.domain.model.DrillGradeResult

/**
 * 打基础页的状态机(计划 §6.4): 纯 Kotlin reducer, 事件进 -> 新状态出,
 * 无 Android/协程依赖, `BriefingReducerTest` 直接锁行为。
 *
 * 口径(与后端 `_reconcile_stage` 对齐):
 * - 当前步 = 清单里第一個 pending 的步, 顺序由服务端 `next_index` 把关;
 * - 60 分过关即翻 passed 并前进; 60 以下**不拦**(留在原地可重录), 只是分数警示;
 * - 跳过额度剩 0 时 UI **前置禁用**跳过键(不等第 3 次吃 409)。
 */
data class BriefingUiState(
    val steps: List<BriefingStepUi> = emptyList(),
    val skipsRemaining: Int = 2,
    val skipLimit: Int = 2,
    val unlockedMission: Boolean = false,
    /** 当前(第一個 pending)步的下标; 全部完成时为 -1。 */
    val currentIndex: Int = -1,
    /** 最近一次评分(属于 answeredStepId 那一步)。 */
    val answeredStepId: String? = null,
    val lastGrade: DrillGradeResult? = null,
    val isSubmitting: Boolean = false,
    val error: String? = null
) {
    val currentStep: BriefingStepUi? get() = steps.getOrNull(currentIndex)

    /** 跳过键可用性: 有额度 + 当前步待做 + 没有在途请求。 */
    val canSkip: Boolean get() = skipsRemaining > 0 && currentStep != null && !isSubmitting

    /** 已走的进度点数量(done = passed + skipped)。 */
    val doneCount: Int get() = steps.count { it.status != "pending" }
}

/** 进度点/列表渲染用的一步。 */
data class BriefingStepUi(
    val id: String,
    val index: Int,
    val type: String,
    val status: String,
    val attempts: Int = 0,
    val bestScore: Double? = null,
    val lastScore: Double? = null,
    val lastSource: String? = null
)

sealed interface BriefingEvent {
    /** 进页/恢复: 用服务端快照整表重建(客户端不自算进度)。 */
    data class Loaded(val briefing: BriefingProgress) : BriefingEvent

    data object SubmitStarted : BriefingEvent

    /** `/step` 或 `/skip-step` 成功返回。 */
    data class Graded(val grade: DrillGradeResult, val briefing: BriefingProgress) : BriefingEvent

    data class Failed(val message: String) : BriefingEvent

    /** 错误提示已被用户看到/处理。 */
    data object ErrorShown : BriefingEvent
}

fun reduceBriefing(state: BriefingUiState, event: BriefingEvent): BriefingUiState = when (event) {
    is BriefingEvent.Loaded -> BriefingUiState(
        steps = event.briefing.steps.map { it.toUi() },
        skipsRemaining = event.briefing.skipsRemaining,
        skipLimit = event.briefing.skipLimit,
        unlockedMission = event.briefing.unlockedMission,
        currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" }
    )

    is BriefingEvent.SubmitStarted -> state.copy(isSubmitting = true, error = null)

    is BriefingEvent.Graded -> BriefingUiState(
        steps = event.briefing.steps.map { it.toUi() },
        skipsRemaining = event.briefing.skipsRemaining,
        skipLimit = event.briefing.skipLimit,
        unlockedMission = event.briefing.unlockedMission,
        currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" },
        answeredStepId = event.grade.stepId,
        lastGrade = event.grade
    )

    is BriefingEvent.Failed -> state.copy(isSubmitting = false, error = event.message)

    is BriefingEvent.ErrorShown -> state.copy(error = null)
}

private fun com.app.english.domain.model.BriefingStepState.toUi(): BriefingStepUi = BriefingStepUi(
    id = id,
    index = index,
    type = type,
    status = status,
    attempts = attempts,
    bestScore = bestScore,
    lastScore = lastScore,
    lastSource = lastSource
)

fun BriefingProgress.toUiState(): BriefingUiState =
    reduceBriefing(BriefingUiState(), BriefingEvent.Loaded(this))
