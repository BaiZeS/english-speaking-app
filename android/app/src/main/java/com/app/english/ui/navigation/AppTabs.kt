package com.app.english.ui.navigation

/** 底部栏图标: 纯配置层用枚举, Compose 侧再映射成 ImageVector(避免导航配置依赖 Compose)。 */
enum class TabIcon { HOME, COURSES, VOCAB, ME }

/**
 * 一个底部 Tab。
 *
 * 这份配置是纯 Kotlin(不 import Compose), 所以 `AppTabsTest` 能在普通 JVM 上断言
 * 「4 个 Tab、顺序、label、route 唯一」—— 也就是计划 §七 P5 的导航静态审查。
 */
data class AppTab(val route: String, val label: String, val icon: TabIcon)

/** 底部 4 Tab(计划 §6.3 顺序): 首页 / 课程 / 词汇 / 我的。 */
val appTabs: List<AppTab> = listOf(
    AppTab(Route.Home.route, "首页", TabIcon.HOME),
    AppTab(Route.Courses.route, "课程", TabIcon.COURSES),
    AppTab(Route.Vocab.route, "词汇", TabIcon.VOCAB),
    AppTab(Route.Me.route, "我的", TabIcon.ME)
)

/** 冷启动落点。(Route.Home.route 是构造属性, 不是编译期常量, 不能标 const。) */
val START_ROUTE: String = Route.Home.route

/** 只有这 4 个目的地显示底部栏。 */
val topLevelRoutes: Set<String> = appTabs.map { it.route }.toSet()

fun tabIndexOf(route: String?): Int = appTabs.indexOfFirst { it.route == route }
