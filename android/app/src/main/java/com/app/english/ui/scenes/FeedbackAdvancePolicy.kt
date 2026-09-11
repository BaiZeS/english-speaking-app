package com.app.english.ui.scenes

import kotlin.math.ceil

/**
 * 高分反馈停留多久、什么时候自动翻下一题(纯 Kotlin, JVM 可测)。
 *
 * **阈值取 85 而不是 60**: 60 是通过线(`PlayerViewModel.MIN_SCORE_TO_ADVANCE`,
 * 语义只是"不拦"), 85 才是本 App 已有的优秀线 —— 与
 * [com.app.english.domain.ScoreColorMapper.GREEN_THRESHOLD]、弱词本毕业线
 * (`MistakeDrillScreen` 的"未达毕业标准(85 分)")同值。**60-84 恰恰是最该读中文
 * 建议的分数带**, 在这个区间自动前进等于把反馈从最需要它的人眼前抽走, 也顺手抹掉
 * "再试一次刷高分"这个自然循环。所以只有到了优秀线才敢在 5 秒后人不在场。
 *
 * **取消与到期不是一回事**(D10): 学员滚动/点按是把反馈留下、自己掌握节奏; 倒计时
 * 自然走完是把反馈让位给下一题。两者都会让 `autoAdvanceSeconds` 变 null, 但只有前者
 * 保留 `pendingGrade`, 所以由两个事件分别表达, 这里只负责算秒数。
 */
object FeedbackAdvancePolicy {
    /** 自动前进的分数线 = 既有的"优秀"绿线, 刻意不是 60 分通过线。 */
    const val AUTO_ADVANCE_SCORE = 85.0

    /** 高分反馈的停留时长。 */
    const val AUTO_ADVANCE_DELAY_MILLIS = 5_000L

    /** 提示上的秒数每一格走多快(与 delay 同源于 [countdownSeconds])。 */
    const val TICK_MILLIS = 1_000L

    /** 过关且够优秀才会自动前进; 未过关永远手动 —— 没过的题不该被翻过去。 */
    fun shouldAutoAdvance(score: Double, passed: Boolean): Boolean =
        passed && score >= AUTO_ADVANCE_SCORE

    /** 停留时长折算成整秒(向上取整, 免得 5s 显示成 4)。 */
    fun countdownSeconds(): Int = ceil(AUTO_ADVANCE_DELAY_MILLIS.toDouble() / TICK_MILLIS).toInt()

    /**
     * 这次评分要不要起倒计时。null = 手动(不画提示、不秒针)。
     */
    fun armSeconds(score: Double, passed: Boolean): Int? =
        if (shouldAutoAdvance(score, passed)) countdownSeconds() else null

    /** 一格秒针之后还剩几秒(null 保持 null: 已取消/未到优秀线不该被复活)。 */
    fun remainingSeconds(secondsLeft: Int?): Int? = secondsLeft?.minus(1)?.coerceAtLeast(0)

    /** 走到 0 的那一格就是自然到期, 由界面据此确认前进(而不是"取消")。 */
    fun isFinished(secondsLeft: Int?): Boolean = secondsLeft == 0

    /** 提示文案: 小字低透明度, 只报"还有几秒"和"怎么留下", 不与反馈正文抢字重。 */
    fun hintLabel(secondsLeft: Int?): String = when {
        secondsLeft == null || secondsLeft <= 0 -> ""
        else -> "$secondsLeft 秒后自动继续 · 点按可停留"
    }
}
