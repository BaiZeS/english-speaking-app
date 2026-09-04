package com.app.english.ui.me

import com.app.english.domain.model.PracticeStats
import com.app.english.ui.components.toRadarValue

/**
 * 能力画像的四维轴(计划 §6.2/§6.4: 发音 / 语法 / 词汇 / 流利度)。
 *
 * `null` = 该维度暂无证据。后端 `GET /ability`(P3/P4 落地)之前语法与词汇确实
 * 没有数据来源, 所以 P5 只用 `GET /stats` 里两个 ISE 维度画一张「不完整」的雷达
 * 并明说缺什么, 而不是拿总平均分凑一个假画像。
 */
data class AbilityAxes(
    val pronunciation: Double? = null,
    val grammar: Double? = null,
    val vocabulary: Double? = null,
    val fluency: Double? = null
) {
    /** 顺序与 [LABELS] 一一对应的原始取值(`null` = 暂无证据)。 */
    private fun values(): List<Double?> = listOf(pronunciation, grammar, vocabulary, fluency)

    /** 四维都有证据才算可用画像; 否则雷达只画得出部分形状。 */
    val isComplete: Boolean get() = values().all { it != null }

    /** 一次练习都没有(雷达应该整个隐藏, 换成引导文案)。 */
    val isEmpty: Boolean get() = values().all { it == null }

    /**
     * 雷达图取值, 顺序与 [LABELS] 一致。
     *
     * 分数域是 0..100(后端所有评分都是这个域), 这里除以 100 变成 0..1 的半径比例;
     * 缺失维度按 0 画(贴着圆心), 不是画到外圈。
     */
    fun radarValues(): List<Float> = values().map { it?.let { v -> v / 100.0 }.toRadarValue() }

    /** 缺失维度的轴名, 界面用它提示「语法 / 词汇 待测评」而不是画假数据。 */
    fun missingLabels(): List<String> = values().mapIndexedNotNull { index, value ->
        if (value == null) LABELS.getOrNull(index) else null
    }

    companion object {
        /** 轴名 + 轴顺序的唯一定义处, 与 [radarValues] 一一对应。 */
        val LABELS: List<String> = listOf("发音", "语法", "词汇", "流利度")

        val EMPTY = AbilityAxes()

        /**
         * P5 的临时画像源: 把练习聚合分映射到能映射的维度。
         *
         * TODO(P7, 计划 §5.6/§6.4): 换成 `GET /ability?device_id=&days=` 返回的
         *  EWMA 画像 + CEFR 定级, 届时 7/30/90 天轨迹与雷达共用同一份数据。
         */
        fun fromStats(stats: PracticeStats?): AbilityAxes {
            if (stats == null || !stats.hasData) return EMPTY
            return AbilityAxes(
                pronunciation = stats.avgPronunciation,
                grammar = null,
                vocabulary = null,
                fluency = stats.avgFluency
            )
        }
    }
}
