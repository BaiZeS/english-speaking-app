package com.app.english.ui.scenes

/**
 * 复盘页的**渲染态与轮询去留**(纯 Kotlin, JVM 可测) —— §P6 客户端第 7/8 项的接缝。
 *
 * 抽出来单独测的理由, 每一条都对应一次真实事故:
 *
 * 1. `review_status` 住在服务端的 JSON 列里, 类型是 `str | None`: 除三种合法值外还可能
 *    出现脏值或字段缺席(旧快照)。这些情况**必须**收敛成"不可知 -> 别再等", 否则就是本
 *    bug 的另一种形状: 复盘页永远转圈。[ReviewPollingPolicy] 的测试锁了"未知状态不轮",
 *    这里锁"未知状态画什么"。
 * 2. 第三态不是"半屏 spinner"。总分/四维/清单/逐词/生词在收工**那次 commit 里就已落库**
 *    (202 之前), 缺的只有两句 AI 文案 —— 所以 `generating` 要照常画数值, 只把文案区换成
 *    进度。整页转圈等于把学员已经到手的成绩藏起来。
 * 3. 判断"文案到没到"只能读 `review_status`, **不能**读 `report.source`: 作业正常跑完而
 *    LLM 挂着时终态是 `ready` + `source == "heuristic"`, 那已经是最终的诚实答案(文案区
 *    自有一枚降级横幅), 不是"还在生成"。
 *
 * 节奏(起探/退避/封顶/放弃水位)一律只取 [ReviewPollingPolicy], 本文件不另立一套。
 */
object ReviewStateMachine {
    /**
     * 连续第 2 次轮询失败就放弃 —— 单次失败按网络抖动放过(与
     * `GenerateCourseViewModel.poll` 同纪律), 一直失败则不要拖着页面不放。
     */
    const val MAX_CONSECUTIVE_POLL_FAILURES = 2

    /**
     * 这一拍之后还要不要再 GET 一次。
     *
     * 判序是刻意的: **超时**排在"状态是不是还允许轮"之前 —— 一份永远停在 `generating`
     * 的快照(进程重启把作业丢了、或重派水位还没到)不该把复盘页钉死在轮询上。数值早已
     * 落库, 放弃等待只是不再追那两句文案。
     */
    fun nextPollStep(
        pollCount: Int,
        elapsedMillis: Long,
        status: String?,
        consecutiveFailures: Int
    ): ReviewPollStep = when {
        ReviewPollingPolicy.isTimedOut(elapsedMillis) ->
            ReviewPollStep.GaveUp(ReviewPollStep.Reason.TIMEOUT)

        consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES ->
            ReviewPollStep.GaveUp(ReviewPollStep.Reason.NETWORK)
        // 只有字面量 `generating` 继续轮: 脏值("running"/"queued"/大小写变体)与字段缺席
        // 一律走 else 停下。一个不认识的状态字符串把循环挂住, 就是"总体评价永远不出来"。
        status == ReviewPollingPolicy.STATUS_GENERATING ->
            ReviewPollStep.Wait(ReviewPollingPolicy.nextDelayMillis(pollCount))

        else -> ReviewPollStep.Stop
    }

    /**
     * 复盘页该画哪一态。
     *
     * [ReviewPhaseInput.hasReport] 是"数值骨架到手没有", 它与 `review_status` 是**两条
     * 独立**的信息: 常态是状态停在 `generating` 而数值早已齐备; 反过来 `review == null`
     * 意味着这一场根本没有可渲染的报告(实战未收工), 那时才只能给整页错误态。
     */
    fun phaseOf(input: ReviewPhaseInput): ReviewPhase = when {
        !input.hasReport -> when {
            // 首个 GET 在途, 或数值骨架还没同步到手机上: 两种都还没东西可画。
            input.awaitingSnapshot -> ReviewPhase.LOADING
            else -> ReviewPhase.NOTHING_TO_RENDER
        }
        // 失败排在生成中之前: 一次已经报失败的作业, 不该因为"循环还挂着"看着仍在等。
        input.status == ReviewPollingPolicy.STATUS_FAILED -> ReviewPhase.COPY_FAILED
        input.status == ReviewPollingPolicy.STATUS_GENERATING ->
            if (input.gaveUpWhileGenerating) ReviewPhase.WAIT_TIMED_OUT else ReviewPhase.GENERATING
        // `ready` 之外还有"脏值"与"字段缺席"两档: 报告已在手上就画它, 不再猜它欠了什么。
        else -> ReviewPhase.FINAL
    }

    /**
     * 这一态要不要把**数值骨架**摆出来(总分圆环 / 四维条 / 任务清单 / 对照 / 生词)。
     *
     * 只有两态不画: 快照还没到手, 以及这一场根本没有报告。`generating` **要**画 —— §P6
     * 的整个取舍都在这里: 数值在 202 之前就 commit 了, 让学员对着一个 spinner 等那两句
     * AI 文案, 等于把他已经拿到的成绩藏起来(而原来的超时界面给人的正是这个感觉)。
     */
    fun paintsReportSkeleton(phase: ReviewPhase): Boolean =
        phase != ReviewPhase.LOADING && phase != ReviewPhase.NOTHING_TO_RENDER

    /**
     * 文案区顶部那句话; null = 这一态不需要进度/占位语。
     *
     * `generating` 用 [ReviewPollingPolicy.stageText](措辞按已等时长变, 不写死"马上好")。
     * 两句放弃语刻意讲清"分数与清单已是本场最终结果, 欠的只是文案" —— 否则学员会以为这
     * 一场白练了, 而这正是他重开 App 后发现"报告一直好好待在那儿"时最火的一种错愕。
     */
    fun proseHintOf(phase: ReviewPhase, elapsedMillis: Long): String? = when (phase) {
        ReviewPhase.GENERATING -> ReviewPollingPolicy.stageText(elapsedMillis)
        ReviewPhase.WAIT_TIMED_OUT ->
            "AI 总评还在写。下面的分数、任务清单与对照已是本场最终结果, 稍后可以再问一次。"

        ReviewPhase.COPY_FAILED ->
            "AI 总评这次没写成。下面的分数、任务清单与对照不受影响, 可以重试。"

        else -> null
    }

    /**
     * 文案区那颗重试键的标签; null = 这一态不放按钮。
     *
     * `generating` 不放: 它自己会好, 而一个"按了只是再 GET 一次"的键会让人以为点一下
     * 才能加速。整页错误态自带重试出口([com.app.english.ui.components.ErrorState]),
     * 所以也不在这里重复。
     */
    fun retryCopyLabelOf(phase: ReviewPhase): String? = when (phase) {
        ReviewPhase.WAIT_TIMED_OUT, ReviewPhase.COPY_FAILED -> "再问一次 AI 总评"
        ReviewPhase.GENERATING, ReviewPhase.LOADING, ReviewPhase.FINAL,
        ReviewPhase.NOTHING_TO_RENDER -> null
    }

    /**
     * 整页错误态要说的话(仅 [ReviewPhase.NOTHING_TO_RENDER]), 其余态返回 null。
     *
     * 这句刻意区分"这场压根没收工"与"收工了但文案还没写": 前者是预期的落差(练完却没报告),
     * 要明说原因并留下重试出口 —— 重试就是再 GET 一次, 服务端会顺手把卡住的作业就地重派,
     * 客户端没有别的调可发。
     */
    fun errorMessageOf(phase: ReviewPhase, networkError: String?): String? = when (phase) {
        ReviewPhase.NOTHING_TO_RENDER ->
            networkError ?: "本场还没有复盘报告 (实战未收工), 点这里重新拉一次"

        else -> null
    }

    /**
     * 「离线降级」横幅只属于终态: 数值骨架的 `source` 恒为 `heuristic`, 生成中挂这句会
     * 把"AI 文案马上到"误报成"这场的文案就是规则拼的"。
     */
    fun showDegradedBanner(phase: ReviewPhase, source: String): Boolean =
        phase == ReviewPhase.FINAL && source != "llm"

    /**
     * `overall == null` 时圆环中心画什么(§P6 次因)。
     *
     * 优先级是刻意的: 有分画分; 没分**且**服务端给了证据说明就画那句说明; 两者都没有才
     * 退回破折号。原先只有最后一档, 于是"讯飞/LLM 都没配, 本场没有可信证据"和"你考了
     * 0 分"在界面上长得一模一样。
     */
    fun overallCenterText(overall: Double?, evidenceNoteCn: String): String = when {
        overall != null -> "${overall.toInt()}"
        evidenceNoteCn.isNotBlank() -> evidenceNoteCn
        else -> "—"
    }

    /** [overallCenterText] 这一次画的是句子而不是分数 —— 字号要降一档才塞得进圆环。 */
    fun overallCenterIsSentence(overall: Double?, evidenceNoteCn: String): Boolean =
        overall == null && evidenceNoteCn.isNotBlank()
}

/** [ReviewStateMachine.nextPollStep] 的结果。 */
sealed interface ReviewPollStep {
    /** 按 [ReviewPollingPolicy] 的退避节奏等一会儿再 GET。 */
    data class Wait(val delayMillis: Long) : ReviewPollStep

    /** 状态已终(含脏值与字段缺席): 停止轮询, 按当前快照渲染。 */
    object Stop : ReviewPollStep

    /**
     * 放弃等待: 同样停止轮询, 但与 [Stop] 的分别是留在类型里的 —— 页面据此在文案区显示
     * "没等到"的可重试提示, 而不是假装一切正常地渲染一份确定版文案。
     */
    data class GaveUp(val reason: Reason) : ReviewPollStep

    enum class Reason { TIMEOUT, NETWORK }
}

/**
 * [ReviewStateMachine.phaseOf] 的输入。
 *
 * 收成一个 data class 而不是一排形参, 一半是为 detekt 的 `LongParameterList`
 * (`functionThreshold: 8`), 另一半是这几个标志**必须**放在一起读: "还在等"与"等放弃了"
 * 是同一件事的两面, 摊成一条布尔参数表最容易写反。
 */
data class ReviewPhaseInput(
    val status: String?,
    val hasReport: Boolean = false,
    /** 首个 GET 还在途(页面什么都没拿到)。 */
    val firstLoadInFlight: Boolean = false,
    /** 轮询循环此刻仍在跑(未终态、未超时、未放弃)。 */
    val pollInFlight: Boolean = false,
    /** 超时或连续网络失败而状态仍停在 `generating`。 */
    val gaveUpWhileGenerating: Boolean = false
) {
    /** 还在等一份能画的东西。 */
    val awaitingSnapshot: Boolean get() = firstLoadInFlight || pollInFlight
}

/** 复盘页的渲染态。 */
enum class ReviewPhase {
    /** 数值还没到手, 整页占位。 */
    LOADING,

    /** 数值已在、AI 文案在写: 数值照常渲染, 只有文案区是进度。 */
    GENERATING,

    /** 文案已定稿(`ready`; 脏值/缺席而报告在手时同样归这一档 —— 不可知就等于不再等)。 */
    FINAL,

    /** 服务端明说作业失败: 数值照画, 文案区给重试出口。 */
    COPY_FAILED,

    /** 等不到文案而放弃: 数值照画, 文案区告诉学员可以再问一次。 */
    WAIT_TIMED_OUT,

    /** 一份报告都没有 -> 整页 [com.app.english.ui.components.ErrorState] + 重试。 */
    NOTHING_TO_RENDER
}
