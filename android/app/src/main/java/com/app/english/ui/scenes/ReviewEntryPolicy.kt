package com.app.english.ui.scenes

/**
 * 「这场练完了, 报告在哪儿」的入口决策(§P6 客户端 9) —— 抽出来是因为它守的是一条
 * **真实的功能缺失**:`SceneDetailViewModel.startLearning()` 只查 `status="active"`,
 * 于是 completed 会话根本查不到 → 唯一的按钮**新开一局**并悄悄丢掉那份报告。
 *
 * 后端早就支持 `GET /sessions?status=completed`, 而 `GET /sessions/{id}` 不按 status 过滤,
 * 所以这是纯客户端活。**不**从历史详情页链回:`History` 表没有 `session_id` 列, 那要迁移,
 * 而本次发版刻意是零迁移的。
 */
object ReviewEntryPolicy {
    const val LABEL_VIEW_LAST_REVIEW = "查看上次复盘"

    /**
     * 详情页主按钮该说什么 —— 三档互斥, 且**绝不**让"看报告"与"开新课"共用一个标签:
     * 一个词根(开始/继续/再练)只描述"进去练", 看复盘永远是另一颗键另一句话。
     */
    fun startLabelOf(hasActiveSession: Boolean, hasCompletedSession: Boolean): String = when {
        hasActiveSession -> "继续学习"
        hasCompletedSession -> "再练一次（新开一局）"
        else -> "开始学习"
    }

    /**
     * 「查看上次复盘」要不要出现。有 finished 场就出现 —— 即使同时存在一条 active 会话:
     * 后者属于**更早**一场练习的报告, 藏起来只会让人以为它随开局丢了。
     */
    fun showReviewEntry(hasCompletedSession: Boolean): Boolean = hasCompletedSession

    /**
     * 从 `GET /sessions?status=completed` 的摘要里挑这一场(或首页:全局)最近一次可回看的
     * 复盘。服务端按 `last_active_at` 倒序返回, 但**不能信**过滤参数一定生效过(旧服务/
     * 代理/以后有人改成不带 status): 只有 `status == "completed"` 的条目才算"有报告可看"。
     * 一场 active/abandoned 会话链到复盘页 = 学员点进一个空壳, 那正是本项要修的东西。
     */
    fun latestReviewSessionId(sessions: List<CompletedSessionRow>): String? =
        sessions.firstOrNull { it.status == "completed" && it.sessionId.isNotBlank() }?.sessionId
}

/** [ReviewEntryPolicy.latestReviewSessionId] 的输入(只取决策要看的三个键)。 */
data class CompletedSessionRow(val sessionId: String, val sceneId: String, val status: String)
