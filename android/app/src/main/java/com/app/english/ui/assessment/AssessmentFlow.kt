package com.app.english.ui.assessment

import com.app.english.domain.model.AssessmentQuestion
import com.app.english.domain.model.abilityDimensionLabel
import kotlin.math.ceil

/**
 * 测评做题页的状态机(计划 §6.4): 纯 Kotlin reducer, 事件进 -> 新状态出,
 * 无 Android/协程依赖, `AssessmentFlowTest` 直接锁行为。
 *
 * 口径(与后端 assessment.py 对齐):
 * - 进度以服务端回执 `answers_count` 为准, 客户端不自算题号;
 * - 音频转写不出(400 TRANSCRIPT_UNAVAILABLE)**不丢题**: 停在原题并点亮
 *   「改用文本」引导, 重答覆盖是后端唯一索引的既有语义;
 * - 最后一题交卷成功即进 JUDGING(批量判级是分钟级调用, UI 挂 spinner),
 *   判级失败退回最后一题允许重试(complete 幂等)。
 */
enum class AssessmentPhase { STARTING, ANSWERING, SUBMITTING, JUDGING, DONE }

data class AssessmentFlowState(
    val phase: AssessmentPhase = AssessmentPhase.STARTING,
    val questions: List<AssessmentQuestion> = emptyList(),
    val index: Int = 0,
    val answeredCount: Int = 0,
    /** 当前题的音频被判「转写不出」—— UI 据此显示改用文本的引导卡。 */
    val audioBlocked: Boolean = false,
    val error: String? = null
) {
    val total: Int get() = questions.size

    val current: AssessmentQuestion? get() = questions.getOrNull(index)

    /** 进度 i/N(题号从 1 数, 服务端 question_no 同口径)。 */
    val progressLabel: String get() = if (total == 0) "" else "${index + 1}/$total"

    val isLast: Boolean get() = total > 0 && index >= total - 1

    /** 文本提交的门槛: 有内容 + 不在途 + 已开考。 */
    val canSubmitText: Boolean get() = phase == AssessmentPhase.ANSWERING
}

sealed interface AssessmentEvent {
    /** 开考成功: 题目清单全量下发。 */
    data class Started(val questions: List<AssessmentQuestion>) : AssessmentEvent

    data object SubmitStarted : AssessmentEvent

    /** `/answer` 成功; answersCount 是服务端权威计数。 */
    data class AnswerAccepted(val answersCount: Int) : AssessmentEvent

    /** 400 TRANSCRIPT_UNAVAILABLE: 本题留在原地, 引导改文本。 */
    data object TranscriptUnavailable : AssessmentEvent

    /** `/complete` 已发出(批量判级中)。 */
    data object CompleteStarted : AssessmentEvent

    /** 判级结果已拿到(DONE 由导航消费)。 */
    data object Judged : AssessmentEvent

    data class Failed(val message: String) : AssessmentEvent

    data object ErrorShown : AssessmentEvent
}

fun reduceAssessment(state: AssessmentFlowState, event: AssessmentEvent): AssessmentFlowState =
    when (event) {
        is AssessmentEvent.Started -> AssessmentFlowState(
            phase = AssessmentPhase.ANSWERING,
            questions = event.questions
        )

        AssessmentEvent.SubmitStarted -> state.copy(
            phase = AssessmentPhase.SUBMITTING,
            error = null
        )

        is AssessmentEvent.AnswerAccepted -> {
            val nextIndex = if (state.isLast) state.index else state.index + 1
            state.copy(
                // 最后一题交卷成功 = 收卷判级开始(VM 紧接着调 /complete)。
                phase = if (state.isLast) AssessmentPhase.JUDGING else AssessmentPhase.ANSWERING,
                index = nextIndex,
                answeredCount = event.answersCount,
                audioBlocked = false,
                error = null
            )
        }

        AssessmentEvent.TranscriptUnavailable -> state.copy(
            phase = AssessmentPhase.ANSWERING,
            audioBlocked = true,
            error = null
        )

        AssessmentEvent.CompleteStarted -> state.copy(phase = AssessmentPhase.JUDGING)

        AssessmentEvent.Judged -> state.copy(phase = AssessmentPhase.DONE, error = null)

        is AssessmentEvent.Failed -> state.copy(
            // 判级中失败也退回 ANSWERING: 题还在原地, 重试即可(complete 幂等)。
            phase = AssessmentPhase.ANSWERING,
            error = event.message
        )

        AssessmentEvent.ErrorShown -> state.copy(error = null)
    }

/** 状态机类错误的 Snackbar/引导文案(按后端 error.code 分支)。 */
fun assessmentErrorCodeText(code: String?, fallback: String?): String = when (code) {
    "TRANSCRIPT_UNAVAILABLE" -> "这段语音没能转写出文字, 试试改用文本作答"
    "ASSESSMENT_ANSWER_REQUIRED" -> "说点什么或写一句再提交"
    "ATTEMPT_NOT_ACTIVE" -> "本次测评已经交过卷了, 直接看结果吧"
    "ATTEMPT_NOT_FOUND" -> "测评会话不存在, 重新开始一次吧"
    "ASSESSMENT_NO_ANSWERS" -> "还没有作答记录, 先答一道题再交卷"
    else -> fallback ?: "提交失败, 请重试"
}

/** 题型中文名(题库的 5 种 QuestionType; 未知类型退回「作答」)。 */
fun assessmentTypeLabel(type: String): String = when (type) {
    "read_aloud" -> "跟读"
    "retell" -> "复述"
    "translate" -> "翻译"
    "open_question" -> "开放问答"
    "quick_chat" -> "快问快答"
    else -> "作答"
}

/** 引导页的时长口径: 逐题秒数求和向上取整, 至少 1 分钟(7 题实测 260s ≈ 5 分钟)。 */
fun estimatedAssessmentMinutes(questions: List<AssessmentQuestion>): Int =
    ceil(questions.sumOf { it.seconds } / 60.0).toInt().coerceAtLeast(1)

/** 结果页四维建议行(顺序与雷达轴一致)。 */
data class DimensionAdvice(
    val dimension: String,
    val label: String,
    val score: Double?,
    val adviceCn: String
)

/**
 * 四维建议(对照「能力测评截图」的文案风格: 一维一句, 先说现状再给动作)。
 * `score = null` 是诚实空态(该维本轮没有可信证据), 不编建议。
 */
fun assessmentDimensionAdvice(dims: Map<String, Double?>): List<DimensionAdvice> =
    listOf("pronunciation", "grammar", "vocabulary", "fluency").map { dimension ->
        val score = dims[dimension]
        DimensionAdvice(
            dimension = dimension,
            label = abilityDimensionLabel(dimension),
            score = score,
            adviceCn = dimensionAdviceCn(dimension, score)
        )
    }

private fun dimensionAdviceCn(dimension: String, score: Double?): String = when {
    score == null -> when (dimension) {
        "pronunciation" -> "本轮没有拿到发音分(跟读题要录真音)。开麦完成跟读, 发音维就有证据了。"
        else -> "本轮没有拿到这一维的可信证据, 补一次练习或测评就会点亮。"
    }
    dimension == "pronunciation" -> when {
        score >= 85 -> "发音很扎实, 注意重音与连读细节就能更上一层。"
        score >= 70 -> "发音清晰。挑几篇课文做影子跟读, 磨平个别吞音。"
        score >= 50 -> "发音有基础。每天 5 分钟跟读, 先求准再求快。"
        else -> "发音还在起步, 从慢速课文跟读开始, 一句一句过。"
    }
    dimension == "grammar" -> when {
        score >= 85 -> "语法功底扎实, 时态与长句都稳, 可以挑战更高级的场景课。"
        score >= 70 -> "语法整体正确, 留意三单、时态这类小错误。"
        score >= 50 -> "基本句型没问题, 复杂从句还会出错, 复盘时多看润色对照。"
        else -> "语法错误较多, 先把课文句型练熟, 再做造句练习。"
    }
    dimension == "vocabulary" -> when {
        score >= 85 -> "词汇量大而且用得准, 试试同义替换升级表达。"
        score >= 70 -> "常用词够用, 每天积累几个新说法收进表达库。"
        score >= 50 -> "核心词汇还行, 卡壳时换个简单说法, 别停下。"
        else -> "词汇量还比较小, 先把情景课的生词表过一遍。"
    }
    else -> when {
        score >= 85 -> "表达流畅自然, 基本不打磕绊, 保持每天的开口节奏。"
        score >= 70 -> "整体流畅, 偶有停顿, 多做限时快问快答。"
        score >= 50 -> "能说但停顿偏多, 用 20 秒小任务练连贯输出。"
        else -> "还不够流利, 跟读加复述是最快的路子, 一天一小段。"
    }
}
