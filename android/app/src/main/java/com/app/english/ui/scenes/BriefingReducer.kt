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
    /**
     * 已作答、学员还没确认的评分。非空时界面**停在这一步的反馈上**, 不前进。
     *
     * 这个槽位存在的唯一理由: 渲染门以前键在 `answeredStepId == spec.id` 上, 而产生
     * 评分的那个事件在同一次归约里就把 `currentIndex` 推到了下一题(计划 R3b)——
     * 也就是"卡片要读的身份被卡片自己的到来作废了", 于是过关时反馈永不出现。
     * 现在门只读 [pendingGrade] 自己, 它只会被
     * [BriefingEvent.FeedbackAcknowledged](点继续 / 倒计时走完)清掉。
     */
    val pendingGrade: DrillGradeResult? = null,
    /** 自动前进还剩几秒; null = 这张反馈不自动翻篇(未达优秀线 / 已被取消 / 重进)。 */
    val autoAdvanceSeconds: Int? = null,
    val isSubmitting: Boolean = false,
    /** 首帧快照是否还没到手。与 `steps.isEmpty()` 合用才能区分"空"的三种含义。 */
    val isLoading: Boolean = true,
    val error: String? = null
) {
    val currentStep: BriefingStepUi? get() = steps.getOrNull(currentIndex)

    /**
     * 题目区该渲染哪一步 —— **反馈优先于游标**。
     *
     * `viewModel.currentSpec()` 解析的是这个, 不是 `currentStep`: 服务端快照仍然是
     * 唯一事实来源(游标照样整表重建), 但屏幕上"正在看的那一题"在反馈停留期间得留在
     * 刚答过的题上, 否则反馈卡就没有宿主。
     */
    val displayedStepId: String? get() = pendingGrade?.stepId ?: currentStep?.id

    /** 反馈正在展示(标题、作答键、跳过行都要据此让位)。 */
    val isAwaitingFeedback: Boolean get() = pendingGrade != null

    /**
     * 现在还能不能作答。**"屏幕上显示的题"和"能提交的题"在反馈停留期间是两回事**:
     *  displayedStepId 是刚答过的那一题, 而服务端只接受下一个 pending 步。反馈没确认
     *  就提交, 发的要么是已经 passed 的步(409 STEP_ALREADY_DONE), 要么是屏幕根本没
     *  显示的那一题(409 STEP_OUT_OF_ORDER)。
     */
    val answerableStepId: String? get() = currentStep?.id?.takeUnless { isAwaitingFeedback }

    /** 「再试一次」只有在**这一步还能再答**时才是真选项(不及格留在原地)。 */
    val canRetryAnsweredStep: Boolean
        get() = pendingGrade?.stepId?.let { id ->
            steps.any { it.id == id && it.status == "pending" }
        }
            ?: false

    /** 倒计时提示文案; 空串 = 不画。 */
    val autoAdvanceHint: String get() = FeedbackAdvancePolicy.hintLabel(autoAdvanceSeconds)

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
    val lastSource: String? = null,
    /**
     * 服务端为这一步留着的完整评分(`step.last_grade`)。以前映射时就丢了, 于是崩溃/
     * 重进之后每步反馈凭空消失 —— 服务端特意逐份存下来正是为了让客户端不用重算。
     */
    val lastGrade: DrillGradeResult? = null
) {
    /** 进度点显示的分: 最好成绩优先, 退回最近一次; 没作答过就画序号/勾。 */
    val dotScore: Double? get() = bestScore ?: lastScore

    /** 刷过两次以上才标, 否则每颗点都挂个 ×1 只是噪声。 */
    val dotAttempts: String?
        get() = attempts.takeIf { it > 1 && dotScore != null }?.let { "×$it" }
}

sealed interface BriefingEvent {
    /** 进页/恢复: 用服务端快照整表重建(客户端不自算进度)。 */
    data class Loaded(val briefing: BriefingProgress) : BriefingEvent

    /** 重新拉快照(错误态的「重试」): 只翻加载旗标, 不清已有清单。 */
    data object Restoring : BriefingEvent

    data object SubmitStarted : BriefingEvent

    /** `/step` 或 `/skip-step` 成功返回。 */
    data class Graded(val grade: DrillGradeResult, val briefing: BriefingProgress) : BriefingEvent

    /**
     * 学员看完了反馈(点「继续」/「再试一次」, 或倒计时自然走完) -> 把屏幕交还游标。
     * `answeredStepId` 只是"这一步刚答过"的语境标记, 与 `pendingGrade` 同生命周期;
     * `lastGrade` 留在状态里当历史(进度点/重绘用), 由下一步的 Graded 覆盖。
     */
    data object FeedbackAcknowledged : BriefingEvent

    /**
     * 学员滚动或点按任意处 -> 只撤掉倒计时, **反馈留在屏上**(D10)。
     *
     * 与 [FeedbackAcknowledged] 分开是因为语义相反: 取消是"我要接着看", 确认是
     * "我看完了"。合成一个事件就等于把"点一下屏幕"当成"把反馈关掉", 正是需求里禁止
     * 的"反馈在阅读时被抽走"。
     */
    data object AutoAdvanceCancelled : BriefingEvent

    /** 秒针走一格(界面每秒推一次; 走到 0 即自然到期, 等价于确认前进)。 */
    data object AutoAdvanceTick : BriefingEvent

    data class Failed(val message: String) : BriefingEvent

    /** 错误提示已被用户看到/处理。 */
    data object ErrorShown : BriefingEvent
}

fun reduceBriefing(state: BriefingUiState, event: BriefingEvent): BriefingUiState = when (event) {
    is BriefingEvent.Loaded -> {
        val steps = event.briefing.steps.map { it.toUi() }
        val currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" }
        val resumed = event.briefing.resumableGrade()
        BriefingUiState(
            steps = steps,
            skipsRemaining = event.briefing.skipsRemaining,
            skipLimit = event.briefing.skipLimit,
            unlockedMission = event.briefing.unlockedMission,
            currentIndex = currentIndex,
            // 崩溃/重进: 服务端逐步存的 last_grade 就是"上次没看完的反馈", 直接摆回去。
            // **不**起倒计时 —— 那 5 秒属于"刚读完这一句"的语境, 隔了一次进程复活再
            // 倒数, 等于在学员没读的时候把反馈抽走。
            answeredStepId = resumed?.stepId,
            lastGrade = resumed,
            pendingGrade = resumed,
            isLoading = false
        )
    }

    is BriefingEvent.Restoring -> state.copy(isLoading = true, error = null)

    is BriefingEvent.SubmitStarted -> state.copy(isSubmitting = true, error = null)

    is BriefingEvent.Graded -> BriefingUiState(
        // 整表照旧由服务端快照重建: 客户端不自算进度, 解耦反馈只是**多**开一个槽位。
        steps = event.briefing.steps.map { it.toUi() },
        skipsRemaining = event.briefing.skipsRemaining,
        skipLimit = event.briefing.skipLimit,
        unlockedMission = event.briefing.unlockedMission,
        currentIndex = event.briefing.steps.indexOfFirst { it.status == "pending" },
        answeredStepId = event.grade.stepId,
        lastGrade = event.grade,
        pendingGrade = event.grade,
        autoAdvanceSeconds = FeedbackAdvancePolicy.armSeconds(
            event.grade.score,
            event.grade.passed
        ),
        isLoading = false
    )

    is BriefingEvent.FeedbackAcknowledged -> state.copy(
        pendingGrade = null,
        autoAdvanceSeconds = null,
        answeredStepId = null
    )

    is BriefingEvent.AutoAdvanceCancelled -> state.copy(autoAdvanceSeconds = null)

    is BriefingEvent.AutoAdvanceTick -> {
        val remaining = FeedbackAdvancePolicy.remainingSeconds(state.autoAdvanceSeconds)
        if (FeedbackAdvancePolicy.isFinished(remaining)) {
            // 自然走完 = 确认前进, 不是取消。
            reduceBriefing(
                state.copy(autoAdvanceSeconds = null),
                BriefingEvent.FeedbackAcknowledged
            )
        } else {
            state.copy(autoAdvanceSeconds = remaining)
        }
    }

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
    lastSource = lastSource,
    lastGrade = lastGrade
)

/**
 * 重进时要摆回屏幕的那份反馈。
 *
 * - 还有待做步 -> 只认**这一步**的 last_grade(崩溃前那次不及格留在原地的反馈);
 * - 清单已跑完 -> 认最后一个有成绩的步, 否则这一屏只剩一个按钮, 刚读过的句子成绩
 *   凭空消失(以前 `|| currentStep == null` 那条死代码想管的正是这个场景)。
 */
private fun BriefingProgress.resumableGrade(): DrillGradeResult? {
    val pending = steps.firstOrNull { it.status == "pending" }
    if (pending != null) return pending.lastGrade
    return steps.lastOrNull { it.lastGrade != null }?.lastGrade
}

fun BriefingProgress.toUiState(): BriefingUiState =
    reduceBriefing(BriefingUiState(), BriefingEvent.Loaded(this))
