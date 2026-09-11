package com.app.english.ui.scenes

import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.ScoreLevel
import com.app.english.domain.model.DrillGradeResult
import com.app.english.domain.model.MissionTurn

/**
 * 评分维度 -> 界面读数的**共用**映射(打基础逐题反馈与实战逐轮反馈同表)。
 *
 * 两条规则都是数据语义, 不是样式选择:
 * 1. **null 一律跳过** —— null 的意思是"这一轮这个维度没有证据"(讯飞没跑 ISE、LLM 没判
 *    语法), 画成 0 就是给学员扣一个没发生的分;
 * 2. **顺序固定** —— 五枚胶囊并排, 标签一律两字: 宽度预算只有播读页三维那排的 3/5,
 *    "流利度"这种三字词在窄屏上会折行, 把整排挤歪。
 */
data class SubScoreReadout(val label: String, val score: Double)

private val SUB_SCORE_DIMENSIONS = listOf(
    "pronunciation" to "发音",
    "fluency" to "流利",
    "completeness" to "完整",
    "grammar" to "语法",
    "vocabulary" to "词汇"
)

/** 服务端 `sub_scores` 那套键(dim -> 分数或 null)。 */
fun subScoreReadout(dims: Map<String, Double?>): List<SubScoreReadout> =
    SUB_SCORE_DIMENSIONS.mapNotNull { (key, label) ->
        dims[key]?.let { SubScoreReadout(label, it) }
    }

/** 一步 drill 的五维 (`DrillGradeResult` 是拆开摆的, 这里收成同一张表)。 */
fun drillSubScoreReadout(grade: DrillGradeResult): List<SubScoreReadout> = subScoreReadout(
    mapOf(
        "pronunciation" to grade.pronunciation,
        "fluency" to grade.fluency,
        "completeness" to grade.completeness,
        "grammar" to grade.grammar,
        "vocabulary" to grade.vocabulary
    )
)

/** 语速读数; 服务端没给就不显示, 不猜。 */
fun speechRateReadout(speechRateWpm: Double?): String? =
    speechRateWpm?.takeIf { it > 0.0 }?.let { "语速 ${it.toInt()} 词/分" }

/**
 * 实战气泡下的一条紧凑发音读数。
 *
 * 实战一屏 6-12 轮, 不能像打基础那样每轮铺开整张反馈卡, 所以只留三样最有用的: 有证据
 * 的维度分、语速、以及**哪几个词没读准**(落在红带的词)。三样全空时返回 null —— 纯文本
 * 轮没有 ISE 证据, 硬画一条空杠就是撒谎。
 */
data class SpeechStrip(
    val dims: List<SubScoreReadout>,
    val rateLabel: String?,
    val weakWords: List<String>
)

fun speechStripOf(turn: MissionTurn): SpeechStrip? {
    val dims = subScoreReadout(turn.subScores)
    val rateLabel = speechRateReadout(turn.speechRateWpm)
    val weakWords = turn.wordDetails
        .filter { ScoreColorMapper.level(it.score) == ScoreLevel.RED }
        .map { it.word }
        .distinct()
    return if (dims.isEmpty() && rateLabel == null && weakWords.isEmpty()) {
        null
    } else {
        SpeechStrip(dims = dims, rateLabel = rateLabel, weakWords = weakWords)
    }
}
