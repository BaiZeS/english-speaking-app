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
 * - 跳过额度剩 0 时 UI **前置禁用**跳过键(不等第 3 次吃 409), 但"为什么禁用"要按
 *   [SkipAffordance] 分开说, 不允许再用一个布尔去贴一句标签。
 */
/**
 * 跳过键的**唯一**可用性判定。
 *
 * 这里曾经只有一个布尔 `canSkip = skipsRemaining > 0 && currentStep != null &&
 * !isSubmitting`, 界面再 `if (canSkip) "跳过这一步" else "跳过额度已用完"` 二选一贴
 * 标签。结果是三种互不相干的原因共用一个词: 学员一松手开始评分
 * (`isSubmitting = true`), 屏幕底部就宣称"跳过额度已用完", 而同屏右上角还印着
 * "跳过额度 2/2"。快照加载失败时(`steps` 为空 -> `currentStep == null`)更是会
 * **永久**误报。一个布尔只表达一件事, 每个原因各给一句真话。
 */
enum class SkipAffordance {
    /** 清单还没到手(加载中 / 加载失败 / 本课无步骤): 不渲染跳过行。 */
    Restoring,

    /** 评分请求在途: 禁用, 文案说"评分中", 不该假称额度问题。 */
    Grading,

    /** 有清单但没有待做步: 禁用, 文案说已完成。 */
    NothingToSkip,

    /** 真的额度用完了(每场 2 次): 禁用并报数。 */
    NoQuota,

    /** 可以跳。 */
    Enabled
}

data class BriefingUiState(
    val steps: List<BriefingStepUi> = emptyList(),
    /**
     * 默认 0 而不是 2: 未加载状态不得对外宣称"还有跳过额度可用"。真值总是由
     * 服务端快照(`Loaded`)覆盖。
     */
    val skipsRemaining: Int = 0,
    val skipLimit: Int = 2,
    val unlockedMission: Boolean = false,
    /** 当前(第一個 pending)步的下标; 全部完成时为 -1。 */
    val currentIndex: Int = -1,
    /** 最近一次评分(属于 answeredStepId 那一步)。 */
    val answeredStepId: String? = null,
    val lastGrade: DrillGradeResult? = null,
    val isSubmitting: Boolean = false,
    /** 首帧快照是否还没到手。与 `steps.isEmpty()` 合用才能区分"空"的三种含义。 */
    val isLoading: Boolean = true,
    val error: String? = null
) {
    val currentStep: BriefingStepUi? get() = steps.getOrNull(currentIndex)

    val skipAffordance: SkipAffordance get() = when {
        steps.isEmpty() -> SkipAffordance.Restoring
        isSubmitting -> SkipAffordance.Grading
        currentStep == null -> SkipAffordance.NothingToSkip
        skipsRemaining <= 0 -> SkipAffordance.NoQuota
        else -> SkipAffordance.Enabled
    }

    /** 跳过键可用性: 只有 `Enabled` 一种原因可以让它可点。 */
    val canSkip: Boolean get() = skipAffordance == SkipAffordance.Enabled

    /** 没有清单可跳时, 这一行整个不渲染(此时 StepCard 自己会说明状态)。 */
    val showsSkipRow: Boolean get() = skipAffordance != SkipAffordance.Restoring

    val skipLabel: String get() = when (skipAffordance) {
        SkipAffordance.Restoring -> ""
        SkipAffordance.Grading -> "评分中…"
        SkipAffordance.NothingToSkip -> "全部步骤已完成"
        SkipAffordance.NoQuota -> "跳过额度已用完 (每场 $skipLimit 次)"
        SkipAffordance.Enabled -> "跳过这一步"
    }

    /**
     * StepCard 题目区在"没有当前步"时的说明。`steps.isEmpty()` 单独判断是不够的:
     * 加载失败与真·已完成都会落在这里, 以前一律写成"正在恢复会话…", 于是加载
     * 失败的画面是"永远在恢复"。
     */
    val emptyStepsExplanation: String get() = when {
        steps.isEmpty() && error != null && !isLoading -> "打基础清单没能加载出来"
        steps.isEmpty() -> "正在恢复会话…"
        else -> "全部步骤已完成"
    }

    /**
     * 快照压根没到手且已经报错: 这一屏无事可做, 要给的是「重试」而不是一个
     * 永远亮着的题目卡 + "正在恢复会话…"。
     */
    val needsSnapshotRetry: Boolean get() = !isLoading && error != null && steps.isEmpty()

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

    /** 重新拉快照(错误态的「重试」): 只翻加载旗标, 不清已有清单。 */
    data object Restoring : BriefingEvent

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
        currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" },
        isLoading = false
    )

    is BriefingEvent.Restoring -> state.copy(isLoading = true, error = null)

    is BriefingEvent.SubmitStarted -> state.copy(isSubmitting = true, error = null)

    is BriefingEvent.Graded -> BriefingUiState(
        steps = event.briefing.steps.map { it.toUi() },
        skipsRemaining = event.briefing.skipsRemaining,
        skipLimit = event.briefing.skipLimit,
        unlockedMission = event.briefing.unlockedMission,
        currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" },
        answeredStepId = event.grade.stepId,
        lastGrade = event.grade,
        isLoading = false
    )

    is BriefingEvent.Failed -> state.copy(
        isSubmitting = false,
        isLoading = false,
        error = event.message
    )

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
