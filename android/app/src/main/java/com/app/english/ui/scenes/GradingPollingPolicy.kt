package com.app.english.ui.scenes

/**
 * §A3 实战判分回填的**去留与状态判据**(纯函数, JVM 可测)。
 *
 * 节奏(起探/退避/封顶/放弃水位)一律只取 [ReviewPollingPolicy] —— 它本来就是"GET
 * `/sessions/{id}` 一直读到某个作业状态落定"的那套节奏, 本文件不另立第二套数字。
 *
 * 三条判据各自对应一次会被写错的地方:
 *
 * 1. **`failed` 不是终点**。服务端在水位过后会就地重派那一轮的判分, 它可能翻身成
 *    `ready` (后端 `SessionView.grading_status` 的注释点名要求客户端别把 `failed` 当
 *    "永远不会再有"而停轮询)。所以循环要继续, 而**界面**那一行同时静默缺省 ——
 *    "没评上"只意味着没有润色, 不是"这一轮不存在", 更不该弹一个「评分失败」。
 * 2. **不认识的状态 = 不可知, 不拿循环去等**。守着 `str | None` 类型的 JSON 列, 脏值
 *    (`"running"`/大小写变体)与字段缺席都会出现; 把它们当 `pending` 就是"永远转圈"的
 *    另一种形状(与 [ReviewStateMachine.nextPollStep] 同一纪律)。`ready` 之外的字面量
 *    一律停。
 * 3. **一次丢包不算放弃**。单次 GET 失败按网络抖动放过(容忍额度 [MAX_CONSECUTIVE_POLL_FAILURES]),
 *    但还没拿到过快照时不能因为"状态是 null"就立刻停 —— 那会把"第一个请求超时"读成
 *    "服务端说不用等了"。
 */
object GradingPollingPolicy {
    const val STATUS_PENDING = "pending"
    const val STATUS_READY = "ready"
    const val STATUS_FAILED = "failed"

    /** 连续第 2 次轮询失败就放弃 (与 `ReviewStateMachine` / `GenerateCourseViewModel` 同纪律)。 */
    const val MAX_CONSECUTIVE_POLL_FAILURES = 2

    /** 这一轮要不要挂「评分生成中…」占位行 (只有字面量 `pending` 算)。 */
    fun isPending(status: String?): Boolean = status == STATUS_PENDING

    /**
     * 会话快照说"还有判分没落" —— 进页面或发完一轮之后要不要起循环看它。
     * `failed` 也算: 它是**这一次**的终态, 但会话级水位过后会被重派。
     */
    fun isAwaiting(status: String?): Boolean = status == STATUS_PENDING || status == STATUS_FAILED

    /** 这一拍之后还要不要再 GET 一次。 */
    fun shouldKeepPolling(
        status: String?,
        sawSnapshot: Boolean,
        consecutiveFailures: Int,
        elapsedMillis: Long
    ): Boolean = when {
        ReviewPollingPolicy.isTimedOut(elapsedMillis) -> false
        consecutiveFailures >= MAX_CONSECUTIVE_POLL_FAILURES -> false
        // 一次快照都没读到: 状态还是"不知道", 别用未知值替服务端下结论。
        !sawSnapshot -> true
        isAwaiting(status) -> true
        // `ready` 收工; 脏值/字段缺席(老会话/旧后端)同样收工。
        else -> false
    }
}
