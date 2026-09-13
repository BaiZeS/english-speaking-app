package com.app.english.ui.assessment

import com.app.english.data.repository.AssessmentRepository
import com.app.english.domain.model.AssessmentJudgement
import kotlinx.coroutines.delay

/**
 * 判级轮询的**节奏策略**(纯函数, JVM 可测; 照 `GeneratePollingPolicy` 的口径)。
 *
 * 服务端判级作业预算 120s(生产实锤: 免费额度限速会把批量判级拖过 20s): 前 3 次每
 * 3s 快探, 之后线性退避到 9s 封顶; 150s 仍无终态按超时放弃 —— 判级作业还在服务端跑,
 * 画像最终会亮, 所以超时文案要按"后台仍在判"措辞而不是报错。
 */
object JudgePollingPolicy {
    const val FAST_POLL_MILLIS = 3_000L
    const val MAX_POLL_MILLIS = 9_000L
    const val TIMEOUT_MILLIS = 150_000L

    /** 第 n 次(n 从 0 起)轮询之后的等待时长。 */
    fun nextDelayMillis(pollCount: Int): Long {
        val delay = FAST_POLL_MILLIS * (pollCount + 1)
        return delay.coerceAtMost(MAX_POLL_MILLIS)
    }

    fun isTimedOut(elapsedMillis: Long): Boolean = elapsedMillis >= TIMEOUT_MILLIS
}

/** 轮询超时的诚实文案: 判级作业仍在后台跑(画像最终会亮), 不是失败。 */
const val JUDGE_STILL_RUNNING_CN = "AI 判级还在后台进行, 完成后可在「我的-能力画像」查看结果。"

/**
 * 轮询判级终态的共享循环(收卷与结果页"重新判级"同一套节奏)。
 * 入参 [first] 是收卷响应里的可能终态(旧后端/幂等回放非空); 返回 null = 超时。
 */
internal suspend fun pollJudgeResult(
    repository: AssessmentRepository,
    attemptId: String,
    first: AssessmentJudgement?
): AssessmentJudgement? {
    var judgement = first
    var pollCount = 0
    val startedAt = System.currentTimeMillis()
    while (judgement == null) {
        if (JudgePollingPolicy.isTimedOut(System.currentTimeMillis() - startedAt)) return null
        delay(JudgePollingPolicy.nextDelayMillis(pollCount++))
        judgement = repository.judgeResult(attemptId)
    }
    return judgement
}
