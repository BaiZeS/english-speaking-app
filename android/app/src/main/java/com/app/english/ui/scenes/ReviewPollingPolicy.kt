package com.app.english.ui.scenes

/**
 * 复盘总评轮询的**节奏策略**(纯函数, JVM 可测)。
 *
 * 与 [GeneratePollingPolicy] 同形但**上限收紧得多**: 选课生成要跑两段 LLM、
 * 全课 5-10 分钟, 而总评只有一次 500-token 文案调用, 实测 ~60-70s 完成 —— 按
 * 分钟级设计节奏会让人在收工后干等。故 2s 起探、线性退避到 6s 封顶、5 分钟
 * 仍无终态即放弃 (报告数值骨架已在 202 之前落库, 放弃轮询只是不再等 AI 文案,
 * 不会丢复盘本身)。
 *
 * 状态字符串与服务端 `doc["review_status"]` 同源, 见
 * `app.api.v1.course_sessions`; 终态只有 `ready` / `failed` 两种, 与生成任务一致。
 */
object ReviewPollingPolicy {
    const val FAST_POLL_MILLIS = 2_000L
    const val MAX_POLL_MILLIS = 6_000L
    const val TIMEOUT_MILLIS = 5 * 60_000L

    const val STATUS_GENERATING = "generating"
    const val STATUS_READY = "ready"
    const val STATUS_FAILED = "failed"

    /** 第 n 次(n 从 0 起)轮询之后的等待时长。 */
    fun nextDelayMillis(pollCount: Int): Long {
        val delay = FAST_POLL_MILLIS * (pollCount + 1)
        return delay.coerceAtMost(MAX_POLL_MILLIS)
    }

    fun isTimedOut(elapsedMillis: Long): Boolean = elapsedMillis >= TIMEOUT_MILLIS

    /** 仍在后台生成 -> 继续轮。`null` 是"根本没在生成"(未收工/旧数据), 不轮。 */
    fun shouldKeepPolling(status: String?): Boolean = status == STATUS_GENERATING

    /** 终态: 有文案 (ready) 或明确失败 (failed), 两者都不再轮询。 */
    fun isTerminal(status: String?): Boolean = status == STATUS_READY || status == STATUS_FAILED

    /** 轮询期间的诚实阶段文案 (服务端没给 stage_text 时兜底)。 */
    fun stageText(elapsedMillis: Long): String =
        if (elapsedMillis >= TIMEOUT_MILLIS / 3) "AI 写得很慢, 再稍等一下" else "AI 正在写总评…"
}
