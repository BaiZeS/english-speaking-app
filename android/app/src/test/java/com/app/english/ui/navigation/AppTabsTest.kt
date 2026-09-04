package com.app.english.ui.navigation

import com.app.english.ui.player.PlayerMode
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 导航配置的静态审查(计划 §七 P5 验收门: 「4 Tab 导航静态审查」)。
 *
 * 底部栏配置与 route 常量都是纯 Kotlin, 所以在 JVM 上就能锁死信息架构:
 * 4 个 Tab、顺序、中文名、route 唯一, 以及旧屏幕的 route 语义没被改坏。
 */
class AppTabsTest {
    @Test
    fun bottomBarHasTheFourPlannedTabsInOrder() {
        assertEquals(4, appTabs.size)
        assertEquals(listOf("首页", "课程", "词汇", "我的"), appTabs.map { it.label })
        assertEquals(
            listOf(Route.Home.route, Route.Courses.route, Route.Vocab.route, Route.Me.route),
            appTabs.map { it.route }
        )
        assertEquals(
            listOf(TabIcon.HOME, TabIcon.COURSES, TabIcon.VOCAB, TabIcon.ME),
            appTabs.map { it.icon }
        )
    }

    @Test
    fun tabRoutesAreUniqueAndCoverTheTopLevelSet() {
        assertEquals(appTabs.size, appTabs.map { it.route }.toSet().size)
        assertEquals(appTabs.map { it.route }.toSet(), topLevelRoutes)
    }

    @Test
    fun startDestinationIsHomeTab() {
        assertEquals(Route.Home.route, START_ROUTE)
        assertTrue(START_ROUTE in topLevelRoutes)
        assertEquals(0, tabIndexOf(START_ROUTE))
        assertEquals(3, tabIndexOf(Route.Me.route))
        assertEquals(-1, tabIndexOf(Route.History.route))
        assertEquals(-1, tabIndexOf(null))
    }

    @Test
    fun navGraphStillRegistersEveryV1Destination() {
        val routes = allRoutes.map { it.route }
        assertEquals("导航图上的目的地总数", allRoutes.size, routes.toSet().size)
        // v1.4 有、v2.0 必须还在的 route(搬家而不是删房间)
        listOf(
            "lesson/{book}/{lessonId}",
            "player/{book}/{lessonId}/{mode}/{roleName}",
            "free_dialogue/{book}/{lessonId}",
            "score_result",
            "history",
            "history_detail",
            "mistake_drill",
            "settings",
            "about"
        ).forEach { legacy ->
            assertTrue("v1 route 丢了: $legacy", legacy in routes)
        }
    }

    @Test
    fun relocatedScreensKeepTheirOwnRoutesOutsideTheTabSet() {
        val relocated = listOf(
            Route.LessonDetail.route,
            Route.Player.route,
            Route.FreeDialogue.route,
            Route.ScoreResult.route,
            Route.History.route,
            Route.HistoryDetail.route,
            Route.MistakeDrill.route,
            Route.Settings.route,
            Route.About.route
        )
        relocated.forEach { route ->
            assertFalse("$route 不应该再是顶层 Tab", route in topLevelRoutes)
            assertTrue(route.isNotEmpty())
        }
        assertEquals(relocated.size, relocated.toSet().size)
    }

    @Test
    fun placeholderRouteNamesMatchThePlan() {
        // 这些名字是 P6/P7 的接接口约定, 改名要同步改计划文档。
        assertEquals("scene_detail/{sceneId}", Route.SceneDetail.route)
        assertEquals("generate_course", Route.GenerateCourse.route)
        assertEquals("assessment_intro", Route.AssessmentIntro.route)
        assertEquals("expressions", Route.ExpressionLibrary.route)
        assertEquals(
            "scene_detail/scene_ordering_coffee",
            Route.SceneDetail.create("scene_ordering_coffee")
        )
    }

    @Test
    fun practiceRoutesKeepTheirArgumentSemantics() {
        assertEquals("lesson/business/12", Route.LessonDetail.create("business", 12))
        assertEquals(
            "free_dialogue/nce1/3",
            Route.FreeDialogue.create("nce1", 3)
        )
        val player = Route.Player.create("nce1", 3, PlayerMode.READ_ALONG)
        assertTrue(player.startsWith("player/nce1/3/"))
        // 没有角色时用占位符, 保证 URL 段数不变
        assertEquals(Route.Player.NO_ROLE, player.substringAfterLast('/'))
        assertNotEquals(
            Route.Player.create("nce1", 3, PlayerMode.DIALOGUE, roleName = "B"),
            player
        )
    }
}
