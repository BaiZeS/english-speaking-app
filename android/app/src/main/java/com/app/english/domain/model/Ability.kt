package com.app.english.domain.model

/**
 * 能力画像与 CEFR 测评的领域形状(计划 §5.6/§5.5-3, P7 消费)。
 *
 * 后端口径(backend ability.py / assessment.py): 四维分 0..100, `null` = 该维
 * 没有被计入的可信证据 —— **别渲染成 0 分**; `cefr_level` 测评前恒 null
 * ("未测评就是未测评"); `band_locked` = 测评后四维等级最多 ±1 档浮动。
 */

/** 四个维度的机器名与固定顺序(与后端 `ability_engine.DIMENSIONS` 一致)。 */
val ABILITY_DIMENSIONS: List<String> = listOf(
    "pronunciation",
    "grammar",
    "vocabulary",
    "fluency"
)

/** 维度机器名 -> 中文名([ABILITY_DIMENSIONS] 同序)。 */
fun abilityDimensionLabel(dimension: String): String = when (dimension) {
    "pronunciation" -> "发音"
    "grammar" -> "语法"
    "vocabulary" -> "词汇"
    "fluency" -> "流利度"
    else -> dimension
}

data class AbilityProfile(
    val pronunciation: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val fluency: Double? = null,
    /** 每维被计入画像的样本数(stub 门控事件不计数)。 */
    val sampleCounts: Map<String, Int> = emptyMap(),
    /** 权威 CEFR 徽章值(测评前 null)。 */
    val cefrLevel: String? = null,
    /** 测评判出的锚(测评写入口, ±1 band 锁的基准)。 */
    val assessmentCefr: String? = null,
    val bandLocked: Boolean = false,
    /** 四维分映射出的辅助等级(不是官方结论)。 */
    val derivedLevel: String? = null,
    val days: Int = 30,
    val trajectory: List<AbilityTrajectoryPoint> = emptyList(),
    val realEvents: Int = 0,
    val userFound: Boolean = false
) {
    /** 测过 = 有判级锚或权威徽章; 空画像(stub/未测评)两个都为 null。 */
    val isAssessed: Boolean get() = assessmentCefr != null || cefrLevel != null

    fun dimension(dimension: String): Double? = when (dimension) {
        "pronunciation" -> pronunciation
        "grammar" -> grammar
        "vocabulary" -> vocabulary
        "fluency" -> fluency
        else -> null
    }

    fun sampleCount(dimension: String): Int = sampleCounts[dimension] ?: 0

    /** 某维是否还没有任何可信证据(n=0)—— 画像页显示「练一轮就有」。 */
    fun lacksEvidence(dimension: String): Boolean = sampleCount(dimension) <= 0

    /**
     * 最弱的维度(今日推荐用它去匹配场景 skills): 只在**有证据**的维里挑最小值,
     * 全空(stub / 什么都没练)返回 null —— 调用方走 curated 兜底, 不假装修推荐。
     * 平分时按 [ABILITY_DIMENSIONS] 固定顺序取先到者。
     */
    fun weakestDimension(): String? = ABILITY_DIMENSIONS
        .mapNotNull { dim -> dimension(dim)?.let { dim to it } }
        .minByOrNull { it.second }
        ?.first
}

/** 轨迹逐日点(只聚合 weight>0 的真实证据, stub 不污染轨迹)。 */
data class AbilityTrajectoryPoint(
    val date: String,
    val pronunciation: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val fluency: Double? = null,
    val events: Int = 0
) {
    fun dimension(dimension: String): Double? = when (dimension) {
        "pronunciation" -> pronunciation
        "grammar" -> grammar
        "vocabulary" -> vocabulary
        "fluency" -> fluency
        else -> null
    }
}

// ====== CEFR 测评(§5.3/§5.5-3) ======

/** 测评一题(题库摘要投影; 参考要点/标准答案永不下发)。 */
data class AssessmentQuestion(
    val id: String,
    val no: Int,
    val type: String,
    val cefrAnchor: String,
    val cnPrompt: String,
    val displayText: String,
    val translationCn: String,
    val seconds: Int
)

/** `GET /assessment` 题库摘要。 */
data class AssessmentBank(val total: Int, val questions: List<AssessmentQuestion>)

/** 开考成功: attempt id 是服务端归属句柄, 题目清单每次全量下发。 */
data class AssessmentSession(
    val attemptId: String,
    val total: Int,
    val questions: List<AssessmentQuestion>
)

/** 逐题作答回执(进度条用 answers_count, 不自算)。 */
data class AssessmentAnswerOutcome(
    val questionNo: Int,
    val answersCount: Int,
    val total: Int,
    val transcript: String
)

/** 测评雷达一轴(score=null = 该维本轮没有证据)。 */
data class AssessmentRadarAxis(
    val dimension: String,
    val score: Double?,
    val max: Double = 100.0,
    val n: Int = 0
)

/** 判级结果; `source="stub"` = LLM 未配置, cefr/dims 全空(诚实空态)。 */
data class AssessmentJudgement(
    val attemptId: String,
    val cefr: String?,
    val dims: Map<String, Double?>,
    val radar: List<AssessmentRadarAxis>,
    val rationaleCn: String,
    val pronunciationSource: String?,
    val source: String,
    val cefrLevel: String?
) {
    val isStub: Boolean get() = source != "llm"

    fun dimension(dimension: String): Double? = dims[dimension]

    fun radarScore(dimension: String): Double? =
        radar.firstOrNull { it.dimension == dimension }?.score
}

/** `POST /polish` 的结果(polish=null = 没问题/LLM 不可用, 看 noteCn)。 */
data class PolishOutcome(
    val polish: PolishSuggestion?,
    val source: String,
    val noteCn: String,
    val expressionId: String?
) {
    val hasPolish: Boolean get() = polish != null && polish.polished.isNotBlank()
}
