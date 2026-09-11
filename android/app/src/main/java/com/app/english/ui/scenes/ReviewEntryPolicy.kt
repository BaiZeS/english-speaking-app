package com.app.english.ui.scenes

import com.app.english.domain.model.ContinueSession

/**
 * 「这一场练完了, 报告在哪儿」的入口决策(§P6 客户端第 9 项) —— 抽出来是因为它守的不是
 * 可发现性, 而是一条**真实的功能缺失**:
 *
 * `SceneDetailViewModel.startLearning()` 与 `HomeViewModel` 都只查 `status = "active"`。
 * 于是一场已 `completed` 的会话在客户端**根本不存在**: 想看刚才那份总评, 唯一能点的按钮
 * 会 `sessionRepository.create(sceneId)` **新开一局并悄悄丢掉那份报告**。复盘页
 * (`Route.SceneReview`) 在MissionScreen 之外没有任何入口, 而进 MissionScreen 需要一条
 * active 会话 —— 报告落库了却回不去。
 *
 * 修法是纯客户端的: 后端 `GET /sessions?status=completed` 早就支持(Z 行按
 * `last_active_at` 倒序), 而 `GET /sessions/{id}` 不按 status 过滤。
 * **[E4] 不要从历史详情页链回** —— `History` 表没有 `session_id` 列, 那需要一次迁移,
 * 而本次发版刻意是零迁移的(计划 §6 风险表)。
 */
object ReviewEntryPolicy {
    /** 详情页那颗回看入口的标签。刻意与"开始/继续/再练"任何一个都不共用词根。 */
    const val LABEL_VIEW_LAST_REVIEW = "查看上次复盘"

    /** 首页入口的标签: 那里不分场景, 说的就是"最近一场练完的"。 */
    const val LABEL_RECENT_REVIEW = "最近复盘"

    /** 服务端 `SessionStatus` 的"打完了"那一档 —— 只有它才有报告可看。 */
    const val STATUS_COMPLETED = "completed"

    /**
     * 详情页主按钮该说什么。三档互斥, 而且**绝不**让"看报告"与"开新课"共用一颗键:
     * 有可回看的旧场时, 主按钮必须自己说清"这是新开一局"(括号那半句就是本次修的误解)。
     */
    fun startLabelOf(hasActiveSession: Boolean, hasCompletedSession: Boolean): String = when {
        hasActiveSession -> "继续学习"
        hasCompletedSession -> "再练一次（新开一局）"
        else -> "开始学习"
    }

    /**
     * 「查看上次复盘」要不要出现。打完过就出现 —— 即使同时存在一条 active 会话:
     * 那条入口指向的是**更早**一场练习的报告, 为了避开"两个按钮一个指向新课一个指向旧报告"
     * 而藏起来, 只会让人以为旧报告随开局丢了(即本项要修的那个误解)。
     */
    fun showReviewEntry(hasCompletedSession: Boolean): Boolean = hasCompletedSession

    /**
     * 从 `GET /sessions` 的摘要里挑最近一场**打完了**的: 首页不分场景, 详情页传 `sceneId`
     * 收窄。服务端已按 `last_active_at` 倒序, 所以"第一个命中"就是"最近一场"。
     *
     * 这里坚持再按 [STATUS_COMPLETED] 自己过滤一遍, 而不是信请求参数: 列表请求可能打在
     * 旧服务端上, 而把一场还在练(或已 abandoned)的会话链到复盘页 = 学员点进一个空壳。
     */
    fun latestCompletedSession(
        sessions: List<ContinueSession>,
        sceneId: String? = null
    ): ContinueSession? = sessions.firstOrNull { row ->
        row.status == STATUS_COMPLETED &&
            row.sessionId.isNotBlank() &&
            (sceneId == null || row.sceneId == sceneId)
    }
}
