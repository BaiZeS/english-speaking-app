package com.app.english.ui.scenes

/**
 * 「收工」这条路径的**点一下算什么**(纯 Kotlin, JVM 可测) —— 计划 §2.6 E2 的接缝。
 *
 * 根因不是文案, 是这条路径**可以重入**: `finishAndReview` 只守卫 `finished`(="服务端已经把
 * 这一场关掉"), 不守卫在途位。于是收工请求还挂在网上时, 学员再点「← 退出」→ 弹窗重新出现
 * → 再点「收工」→ 并发第二个请求。生产日志里那 4 连 409 就是这么来的: 超时路径下
 * `finished` 永远是 false, 整条退出链路持续可重入。异步化把窗口从 ~60s 收到亚秒级,
 * 但守卫**仍然必须存在** —— 慢链路与网络抖动下同样会重复提交。
 *
 * 两条刻意的判序:
 * 1. **在途排在 `finished` 之前**。反过来会把"其实已经收工"的学员再发一次请求, 吃一个 409
 *    才跳复盘页 —— 白跑一趟, 还多一条红字。
 * 2. **不复用 `finished` 当在途标志**。它的语义是"服务端关掉了这一场", 与"我的请求还在天上"
 *    是两件事; 把两者捏成一个布尔, 正是原 bug 的形状。在途位取 `MissionUiState.inFlight`
 *    (= 发一轮 OR 要提示 OR 收工), 界面另用 `isFinishing` 单独驱动弹窗与重试出口。
 */
object MissionFinishGuard {
    /**
     * 服务端"这一场早就收过了"的错误码 —— 幂等场景, 该跳复盘页而不是报错。
     *
     * **两个码都要认**, 这是端到端冒烟实测出来的(2026-09-11, 本机真火): 后端
     * `_require_mission_actionable` 的判序是 `status != "active"` → `SESSION_NOT_ACTIVE`
     * **先于** `stage in ("review","done")` → `MISSION_FINISHED`, 而收工会同时置
     * `status="completed"` 与 `stage="review"`, 所以对一场**已经收工成功**的会话再收一次,
     * 拿到的永远是 `SESSION_NOT_ACTIVE`, `MISSION_FINISHED` 那条分支根本不可达。
     * 只认 `MISSION_FINISHED` 等于把幂等恢复路径写成死代码 —— 而它要救的恰恰是生产事故
     * 那个形状: 请求其实成了、响应没回到手机上(session 719833d1 的 `200 OK` 从未打印,
     * 学员随后 4 连点吃 4 个 409), 此时报告已落库, 该做的是把人送进复盘页, 不是甩一句
     * "本场会话已结束"让他以为成绩没了。
     *
     * 认 `SESSION_NOT_ACTIVE` 是安全的: 全后端只有 `active → completed` 一条状态迁移,
     * `abandoned` 从未被任何代码置上(只存在于 `models/db.py` 的取值注释里), 所以这个码
     * 在实践中只可能意味着"已收工"。万一真遇到没有报告的会话, 复盘页自己会渲染可重试的
     * 空态, 不会白屏。
     */
    val CODES_ALREADY_FINISHED = setOf("MISSION_FINISHED", "SESSION_NOT_ACTIVE")

    /** 点「收工」/调 `finishAndReview` 那一刻的处置。 */
    fun tapOf(finished: Boolean, inFlight: Boolean): FinishTap = when {
        inFlight -> FinishTap.IGNORE_IN_FLIGHT
        finished -> FinishTap.OPEN_REVIEW
        else -> FinishTap.SUBMIT
    }

    /**
     * 「← 退出」能不能把收工弹窗**重新**打开: 收工在途时不能再开。
     *
     * 只挡收工、不挡"发一轮在途" —— 后者可以挂到 23s(一轮 IAT + 判分), 那时把退出按钮
     * 打死会让人连"算了, 收工"都按不到, 用一个更糟的体验去换一个更安全的体验。
     */
    fun canOpenExitDialog(isFinishing: Boolean): Boolean = !isFinishing

    /**
     * 失败是不是"幂等成功"。409 [CODES_ALREADY_FINISHED] 说明服务端已经关掉了这一场 ——
     * 多半是上一次请求其实成了, 只是响应没能回到这台手机上。
     */
    fun failureMeansAlreadyFinished(code: String?): Boolean = code in CODES_ALREADY_FINISHED
}

/** [MissionFinishGuard.tapOf] 的结果。 */
enum class FinishTap {
    /** 有请求在途: 什么都不做(不弹窗、不再发一个)。 */
    IGNORE_IN_FLIGHT,

    /** 服务端已收工: 直接进复盘页, 不再发请求。 */
    OPEN_REVIEW,

    /** 该发一次 `POST /sessions/{id}/finish-mission`。 */
    SUBMIT
}
