package com.app.english.ui.scenes

import com.app.english.domain.model.GenerationJob
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.TaskChip

/**
 * 生成课轮询的**节奏策略**(纯函数, JVM 可测)。
 *
 * T5 实测(2026-09-05): 免费额度下每段 200-240s, 全课 5-10 分钟 —— 客户端进度
 * 按**分钟级**诚实设计: 前 3 次每 4s 快探, 之后线性退避到 12s 封顶; 15 分钟仍无
 * 终态按超时放弃(生成任务还在服务端跑, 失败页引导稍后重试而不是反复起 job)。
 */
object GeneratePollingPolicy {
    const val FAST_POLL_MILLIS = 4_000L
    const val MAX_POLL_MILLIS = 12_000L
    const val TIMEOUT_MILLIS = 15 * 60_000L

    /** 第 n 次(n 从 0 起)轮询之后的等待时长。 */
    fun nextDelayMillis(pollCount: Int): Long {
        val delay = FAST_POLL_MILLIS * (pollCount + 1)
        return delay.coerceAtMost(MAX_POLL_MILLIS)
    }

    fun isTimedOut(elapsedMillis: Long): Boolean = elapsedMillis >= TIMEOUT_MILLIS

    /** 三段进度文案(理解目标→设计任务→生成对话), 服务端 stage_text 为主、这里兜底。 */
    fun stageIndex(progress: Double): Int = when {
        progress < 0.4 -> 0
        progress < 0.8 -> 1
        else -> 2
    }

    fun isTerminal(job: GenerationJob): Boolean = job.isReady || job.isFailed
}

/**
 * 实战页「润色嵌在用户气泡下」的数据映射(纯函数, JVM 可测)。
 *
 * 规则: 没有 polish、或润色句与原句完全相同(LLM 判为无需修改时的退化返回),
 * 气泡不渲染; polish 一定来自服务端真值, 客户端不再编造占位文案。
 */
data class PolishBubble(val original: String, val polished: String, val explanationCn: String) {
    val isOriginalWorse: Boolean get() = original.isNotBlank() && polished.isNotBlank()
}

fun PolishSuggestion?.toBubbleOrNull(): PolishBubble? {
    val polish = this ?: return null
    if (polish.polished.isBlank()) return null
    if (polish.polished.trim() == polish.original.trim()) return null
    return PolishBubble(
        original = polish.original,
        polished = polish.polished,
        explanationCn = polish.explanationCn
    )
}

/** HUD 计数: 已勾 m / 任务总数 k(必做+选做都算, 与后端 checklist 同口径)。 */
fun taskProgressLabel(checklist: List<TaskChip>): String =
    "${checklist.count { it.done }}/${checklist.size}"
