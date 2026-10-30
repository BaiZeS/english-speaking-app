package com.app.english.ui.navigation

/**
 * v3.0 的导航目的地 —— 只剩 4 个 (旧版是 4 Tab + 23 个目的地)。
 *
 * 单词/课程/跟读/测评/统计那批屏幕随功能一起从产品里删除, 所以这里**没有**它们的
 * 残留 route: 留着会让"这个入口还有没有必要"变成每次改动都要重新考古的问题。
 *
 * 底部 Tab 也一起退役 —— 会话列表就是首页, 设置从列表右上角进。
 */
sealed class Route(val route: String) {
    /** 根屏: 微信式会话列表 (= 场景列表)。 */
    data object ThreadList : Route("chat_list")

    /** 一个场景的群聊。`sceneKey` 不是线程 id —— 开线程是幂等的, 由界面自己拿到 id。 */
    data object Chat : Route("chat/{sceneKey}") {
        const val ARG_SCENE_KEY = "sceneKey"
        fun create(sceneKey: String): String = "chat/$sceneKey"
    }

    /**
     * 设置 —— **必须保留的逃生门**。v2.2.4 的教训: 更新检查失败时弹窗要能关, 且要能
     * 进设置改服务器地址, 否则后端不可达时用户被模态框锁死在所有页面之外。
     */
    data object Settings : Route("settings")

    data object About : Route("about")
}

/** 冷启动落点。 */
val START_ROUTE: String = Route.ThreadList.route
