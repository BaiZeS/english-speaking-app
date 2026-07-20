package com.app.english.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Insights
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.app.english.ui.freedialogue.FreeDialogueScreen
import com.app.english.ui.history.HistoryDetailScreen
import com.app.english.ui.history.HistoryListScreen
import com.app.english.ui.lesson.LessonDetailScreen
import com.app.english.ui.lessons.LessonListScreen
import com.app.english.ui.player.PlayerScreen
import com.app.english.ui.score.ScoreResultScreen
import com.app.english.ui.settings.SettingsScreen

private data class TopDestination(val route: String, val label: String, val icon: ImageVector)

private val topDestinations = listOf(
    TopDestination(Route.Dashboard.route, "概览", Icons.Filled.Insights),
    TopDestination(Route.Lessons.route, "课文", Icons.Filled.MenuBook),
    TopDestination(Route.History.route, "历史", Icons.Filled.History),
    TopDestination(Route.Settings.route, "设置", Icons.Filled.Settings)
)

@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBottomBar = currentRoute in topLevelRoutes

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    topDestinations.forEach { dest ->
                        NavigationBarItem(
                            selected = currentRoute == dest.route,
                            onClick = {
                                navController.navigate(dest.route) {
                                    popUpTo(Route.Dashboard.route) { saveState = true }
                                    launchSingleTop = true
                                    restoreState = true
                                }
                            },
                            icon = { Icon(dest.icon, contentDescription = dest.label) },
                            label = { Text(dest.label) }
                        )
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = Route.Dashboard.route,
            modifier = Modifier.padding(padding)
        ) {
            composable(Route.Dashboard.route) {
                DashboardScreen(
                    onHistoryClick = {
                        navController.navigate(Route.History.route) {
                            popUpTo(Route.Dashboard.route) { saveState = true }
                            launchSingleTop = true
                            restoreState = true
                        }
                    }
                )
            }
            composable(Route.Lessons.route) {
                LessonListScreen(
                    onLessonClick = { id -> navController.navigate(Route.LessonDetail.create(id)) }
                )
            }
            composable(
                route = Route.LessonDetail.route,
                arguments = listOf(
                    navArgument(Route.LessonDetail.ARG_LESSON_ID) {
                        type =
                            NavType.IntType
                    }
                )
            ) {
                LessonDetailScreen(
                    onBack = { navController.popBackStack() },
                    onStartPractice = { lessonId, mode ->
                        navController.navigate(Route.Player.create(lessonId, mode))
                    },
                    onStartFreeDialogue = { lessonId ->
                        navController.navigate(Route.FreeDialogue.create(lessonId))
                    }
                )
            }
            composable(
                route = Route.Player.route,
                arguments = listOf(
                    navArgument(Route.Player.ARG_LESSON_ID) { type = NavType.IntType },
                    navArgument(Route.Player.ARG_MODE) { type = NavType.StringType },
                    navArgument(Route.Player.ARG_ROLE_NAME) { type = NavType.StringType }
                )
            ) {
                PlayerScreen(
                    onBack = { navController.popBackStack() },
                    onFinish = {
                        navController.navigate(Route.ScoreResult.route) {
                            popUpTo(Route.Lessons.route)
                        }
                    }
                )
            }
            composable(
                route = Route.FreeDialogue.route,
                arguments = listOf(
                    navArgument(Route.FreeDialogue.ARG_LESSON_ID) { type = NavType.IntType }
                )
            ) {
                FreeDialogueScreen(
                    onBack = { navController.popBackStack() },
                    onFinish = {
                        navController.navigate(Route.ScoreResult.route) {
                            popUpTo(Route.Lessons.route)
                        }
                    }
                )
            }
            composable(Route.ScoreResult.route) {
                ScoreResultScreen(
                    onDone = {
                        navController.navigate(Route.Lessons.route) {
                            popUpTo(Route.Lessons.route) { inclusive = true }
                            launchSingleTop = true
                        }
                    }
                )
            }
            composable(Route.History.route) {
                HistoryListScreen(
                    onItemClick = { navController.navigate(Route.HistoryDetail.route) }
                )
            }
            composable(Route.HistoryDetail.route) {
                HistoryDetailScreen(onBack = { navController.popBackStack() })
            }
            composable(Route.Settings.route) {
                SettingsScreen()
            }
        }
    }
}
