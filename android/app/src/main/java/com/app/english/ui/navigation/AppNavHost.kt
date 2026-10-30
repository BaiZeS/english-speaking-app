package com.app.english.ui.navigation

import androidx.compose.runtime.Composable
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.app.english.ui.about.AboutScreen
import com.app.english.ui.chat.ChatScreen
import com.app.english.ui.chat.ThreadListScreen
import com.app.english.ui.settings.SettingsScreen

/**
 * 整张导航图: 会话列表 -> 群聊, 外加设置与关于。
 *
 * 没有底部栏、没有 Tab 栈 —— [Route.ThreadList] 就是首页。
 */
@Composable
fun AppNavHost(navController: NavHostController = rememberNavController()) {
    NavHost(navController = navController, startDestination = START_ROUTE) {
        composable(Route.ThreadList.route) {
            ThreadListScreen(
                onOpenScene = { sceneKey ->
                    navController.navigate(Route.Chat.create(sceneKey))
                },
                onOpenSettings = { navController.openSettingsScreen() }
            )
        }
        composable(
            route = Route.Chat.route,
            arguments = listOf(navArgument(Route.Chat.ARG_SCENE_KEY) { type = NavType.StringType })
        ) { entry ->
            ChatScreen(
                sceneKey = entry.arguments?.getString(Route.Chat.ARG_SCENE_KEY).orEmpty(),
                onBack = { navController.popBackStack() }
            )
        }
        composable(Route.Settings.route) {
            SettingsScreen(onAboutClick = { navController.navigate(Route.About.route) })
        }
        composable(Route.About.route) {
            AboutScreen(onBack = { navController.popBackStack() })
        }
    }
}

/**
 * 逃生门的唯一入口: 更新检查失败弹窗上的「进入设置」。
 *
 * 旧实现先 `navigateToTab(Route.Me.route)` 再进设置 (那时设置挂在「我的」Tab 下);
 * Tab 退役之后这里就只剩一步 —— 少一步就少一种"弹窗关了但页面没到"的失败形状。
 */
fun NavHostController.openSettingsScreen() {
    navigate(Route.Settings.route) { launchSingleTop = true }
}
