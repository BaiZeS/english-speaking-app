package com.app.english.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * v3.0 导航的静态审查。
 *
 * 这个文件原来叫 `AppTabsTest` 并钉着"4 个底部 Tab、顺序、label、route 唯一"。
 * 底部栏整个退役了, 所以它现在钉的是**只剩 4 个目的地、根是会话列表、没有 Tab**,
 * 以及那扇不能丢的逃生门。名字先留着: 改文件名会让 blame 历史断掉, 而它仍是
 * "导航配置层的机器审查"这一件事。
 */
class AppTabsTest {
    @Test
    fun `route list is exactly the four v3 destinations`() {
        val routes = listOf(
            Route.ThreadList.route,
            Route.Chat.route,
            Route.Settings.route,
            Route.About.route
        )
        assertEquals(4, routes.size)
        assertEquals("no duplicate route", routes.toSet().size, routes.size)
    }

    @Test
    fun `cold start lands on the chat list`() {
        // 单词/课程/测评退役后没有"首页"可去了: 列表就是首页。
        assertEquals("chat_list", START_ROUTE)
        assertEquals(Route.ThreadList.route, START_ROUTE)
    }

    @Test
    fun `chat route carries the scene key`() {
        assertEquals("chat/restaurant", Route.Chat.create("restaurant"))
        assertTrue(Route.Chat.route.contains(Route.Chat.ARG_SCENE_KEY))
    }

    @Test
    fun `settings stays reachable as the escape hatch`() {
        // v2.2.4 的教训: 更新检查失败时如果进不了设置 (服务器地址只在那儿改),
        // 用户会被模态框锁死在所有页面之外。这扇门一旦丢, 后端不可达就等于 App 变砖。
        assertEquals("settings", Route.Settings.route)
    }
}
