package com.app.english.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Icon
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.navigation.NavGraphBuilder
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import com.app.english.ui.about.AboutScreen
import com.app.english.ui.assessment.AssessmentIntroScreen
import com.app.english.ui.assessment.AssessmentResultScreen
import com.app.english.ui.assessment.AssessmentScreen
import com.app.english.ui.courses.CourseHubScreen
import com.app.english.ui.drill.MistakeDrillScreen
import com.app.english.ui.expressions.ExpressionLibraryScreen
import com.app.english.ui.freedialogue.FreeDialogueScreen
import com.app.english.ui.history.HistoryDetailScreen
import com.app.english.ui.history.HistoryListScreen
import com.app.english.ui.home.HomeScreen
import com.app.english.ui.lesson.LessonDetailScreen
import com.app.english.ui.me.AbilityProfileScreen
import com.app.english.ui.me.MeScreen
import com.app.english.ui.player.PlayerScreen
import com.app.english.ui.scenes.BriefingScreen
import com.app.english.ui.scenes.GenerateCourseScreen
import com.app.english.ui.scenes.MissionScreen
import com.app.english.ui.scenes.ReviewScreen
import com.app.english.ui.scenes.SceneDetailScreen
import com.app.english.ui.score.ScoreResultScreen
import com.app.english.ui.settings.SettingsScreen
import com.app.english.ui.vocab.VocabHubScreen

/**
 * v2.0 导航图(计划 §6.3)。
 *
 * 4 个底部 Tab 各是一个目的地; v1 的屏幕全部挂在同一张图上, 只是入口从「概览页」
 * 换成了新的 hub。练习链路(player / free_dialogue / score_result)的参数与跳转
 * 语义和 v1.4 一致, 只是回退锚点从旧的 `lessons` 变成了 `courses` Tab。
 */
@Composable
fun AppNavHost() {
    val navController = rememberNavController()
    val backStackEntry by navController.currentBackStackEntryAsState()
    val currentRoute = backStackEntry?.destination?.route
    val showBottomBar = currentRoute in topLevelRoutes
    // 首页分类卡 -> 课程 Tab 的一次性筛选交接(Tab 之间没有父子导航关系)。
    var pendingCategory by remember { mutableStateOf<String?>(null) }

    Scaffold(
        bottomBar = {
            if (showBottomBar) {
                NavigationBar {
                    appTabs.forEach { tab ->
                        NavigationBarItem(
                            selected = currentRoute == tab.route,
                            onClick = { navController.navigateToTab(tab.route) },
                            icon = { Icon(tab.icon.vector(), contentDescription = tab.label) },
                            label = { Text(tab.label) }
                        )
                    }
                }
            }
        }
    ) { padding ->
        NavHost(
            navController = navController,
            startDestination = START_ROUTE,
            modifier = Modifier.padding(padding)
        ) {
            homeTab(navController) { category ->
                pendingCategory = category
                navController.navigateToTab(Route.Courses.route)
            }
            coursesTab(
                navController = navController,
                // 用 provider 而不是值: NavHost 的图只在首次组合时构建一次, 直接传值
                // 会把 pendingCategory 永远钉成 null。
                pendingCategory = { pendingCategory },
                onCategoryConsumed = { pendingCategory = null }
            )
            vocabTab(navController)
            meTab(navController)
            lessonGraph(navController)
            sceneGraph(navController)
            assessmentGraph(navController)
        }
    }
}

/** 底部栏切换: 回到起点并保存/恢复各 Tab 自己的栈(4 个 Tab 之间互不污染)。 */
private fun NavHostController.navigateToTab(route: String) {
    navigate(route) {
        popUpTo(START_ROUTE) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }
}

private fun TabIcon.vector(): ImageVector = when (this) {
    TabIcon.HOME -> Icons.Filled.Home
    TabIcon.COURSES -> Icons.Filled.School
    TabIcon.VOCAB -> Icons.Filled.CollectionsBookmark
    TabIcon.ME -> Icons.Filled.Person
}

private fun NavGraphBuilder.homeTab(
    navController: NavHostController,
    onCategoryClick: (String) -> Unit
) {
    composable(Route.Home.route) {
        HomeScreen(
            onSceneClick = { sceneId ->
                navController.navigate(Route.SceneDetail.create(sceneId))
            },
            onCategoryClick = onCategoryClick,
            onGenerateCourseClick = { navController.navigate(Route.GenerateCourse.route) },
            onAssessmentClick = { navController.navigate(Route.AssessmentIntro.route) }
        )
    }
}

private fun NavGraphBuilder.coursesTab(
    navController: NavHostController,
    pendingCategory: () -> String?,
    onCategoryConsumed: () -> Unit
) {
    composable(Route.Courses.route) {
        CourseHubScreen(
            onSceneClick = { sceneId ->
                navController.navigate(Route.SceneDetail.create(sceneId))
            },
            onLessonClick = { book, lessonId ->
                navController.navigate(Route.LessonDetail.create(book, lessonId))
            },
            initialCategory = pendingCategory(),
            onCategoryConsumed = onCategoryConsumed
        )
    }
}

private fun NavGraphBuilder.vocabTab(navController: NavHostController) {
    composable(Route.Vocab.route) {
        VocabHubScreen(
            onExpressionLibraryClick = { navController.navigate(Route.ExpressionLibrary.route) },
            onDrillClick = { navController.navigate(Route.MistakeDrill.route) }
        )
    }
}

private fun NavGraphBuilder.meTab(navController: NavHostController) {
    composable(Route.Me.route) {
        MeScreen(
            onHistoryClick = { navController.navigate(Route.History.route) },
            onSettingsClick = { navController.navigate(Route.Settings.route) },
            onAboutClick = { navController.navigate(Route.About.route) },
            onAssessmentClick = { navController.navigate(Route.AssessmentIntro.route) },
            onProfileClick = { navController.navigate(Route.AbilityProfile.route) }
        )
    }
}

/** 课本链路: 课文详情 -> 四种练习模式 / 自由对话 -> 成绩页。语义与 v1.4 相同。 */
private fun NavGraphBuilder.lessonGraph(navController: NavHostController) {
    composable(
        route = Route.LessonDetail.route,
        arguments = listOf(
            navArgument(Route.LessonDetail.ARG_BOOK) { type = NavType.StringType },
            navArgument(Route.LessonDetail.ARG_LESSON_ID) { type = NavType.IntType }
        )
    ) {
        LessonDetailScreen(
            onBack = { navController.popBackStack() },
            onStartPractice = { book, lessonId, mode ->
                navController.navigate(Route.Player.create(book, lessonId, mode))
            },
            onStartFreeDialogue = { book, lessonId ->
                navController.navigate(Route.FreeDialogue.create(book, lessonId))
            }
        )
    }
    composable(
        route = Route.Player.route,
        arguments = listOf(
            navArgument(Route.Player.ARG_BOOK) { type = NavType.StringType },
            navArgument(Route.Player.ARG_LESSON_ID) { type = NavType.IntType },
            navArgument(Route.Player.ARG_MODE) { type = NavType.StringType },
            navArgument(Route.Player.ARG_ROLE_NAME) { type = NavType.StringType }
        )
    ) {
        PlayerScreen(
            onBack = { navController.popBackStack() },
            onFinish = {
                navController.navigate(Route.ScoreResult.route) {
                    popUpTo(Route.Courses.route)
                }
            }
        )
    }
    composable(
        route = Route.FreeDialogue.route,
        arguments = listOf(
            navArgument(Route.FreeDialogue.ARG_BOOK) { type = NavType.StringType },
            navArgument(Route.FreeDialogue.ARG_LESSON_ID) { type = NavType.IntType }
        )
    ) {
        FreeDialogueScreen(
            onBack = { navController.popBackStack() },
            onFinish = {
                navController.navigate(Route.ScoreResult.route) {
                    popUpTo(Route.Courses.route)
                }
            }
        )
    }
    composable(Route.ScoreResult.route) {
        ScoreResultScreen(
            onDone = {
                navController.navigate(Route.Courses.route) {
                    popUpTo(Route.Courses.route) { inclusive = true }
                    launchSingleTop = true
                }
            }
        )
    }
    composable(Route.History.route) {
        HistoryListScreen(onItemClick = { navController.navigate(Route.HistoryDetail.route) })
    }
    composable(Route.HistoryDetail.route) {
        HistoryDetailScreen(onBack = { navController.popBackStack() })
    }
    composable(Route.MistakeDrill.route) {
        MistakeDrillScreen(onBack = { navController.popBackStack() })
    }
    composable(Route.AbilityProfile.route) {
        AbilityProfileScreen(onBack = { navController.popBackStack() })
    }
    composable(Route.Settings.route) {
        SettingsScreen(onAboutClick = { navController.navigate(Route.About.route) })
    }
    composable(Route.About.route) {
        AboutScreen(onBack = { navController.popBackStack() })
    }
}

/**
 * P6 情景课全流程的目的地(替换 P5 占位); 测评与表达库仍是 P7 占位。
 */
private fun NavGraphBuilder.sceneGraph(navController: NavHostController) {
    composable(
        route = Route.SceneDetail.route,
        arguments = listOf(
            navArgument(Route.SceneDetail.ARG_SCENE_ID) { type = NavType.StringType }
        )
    ) {
        SceneDetailScreen(
            onBack = { navController.popBackStack() },
            onOpenBriefing = { sessionId ->
                navController.navigate(Route.SceneBriefing.create(sessionId))
            },
            onOpenMission = { sessionId ->
                navController.navigate(Route.SceneMission.create(sessionId))
            }
        )
    }
    composable(Route.GenerateCourse.route) {
        GenerateCourseScreen(
            onBack = { navController.popBackStack() },
            onCourseReady = { sceneId ->
                // 生成课在画廊里已可见(合并自 DB), 打开它的详情页。
                navController.navigate(Route.SceneDetail.create(sceneId)) {
                    popUpTo(Route.Home.route)
                }
            }
        )
    }
    composable(
        route = Route.SceneBriefing.route,
        arguments = listOf(
            navArgument(Route.SceneBriefing.ARG_SESSION_ID) { type = NavType.StringType }
        )
    ) {
        BriefingScreen(
            onBack = { navController.popBackStack() },
            onOpenMission = { sessionId ->
                navController.navigate(Route.SceneMission.create(sessionId)) {
                    // 打基础一走完, 返回栈里不需要再留它(回退锚点是课程详情)。
                    popUpTo(Route.SceneDetail.route)
                }
            }
        )
    }
    composable(
        route = Route.SceneMission.route,
        arguments = listOf(
            navArgument(Route.SceneMission.ARG_SESSION_ID) { type = NavType.StringType }
        )
    ) {
        MissionScreen(
            onBack = { navController.popBackStack() },
            onOpenReview = { sessionId ->
                navController.navigate(Route.SceneReview.create(sessionId)) {
                    popUpTo(Route.SceneDetail.route)
                }
            }
        )
    }
    composable(
        route = Route.SceneReview.route,
        arguments = listOf(
            navArgument(Route.SceneReview.ARG_SESSION_ID) { type = NavType.StringType }
        )
    ) {
        ReviewScreen(
            onBack = { navController.popBackStack() },
            onReplay = { sceneId ->
                navController.navigate(Route.SceneDetail.create(sceneId)) {
                    popUpTo(Route.Home.route)
                }
            }
        )
    }
}

/**
 * P7 的测评链路与表达库(替换 P5 占位); 做题路由不带载荷, 判级结果经
 * `AssessmentResultHolder` 单例交接。
 */
private fun NavGraphBuilder.assessmentGraph(navController: NavHostController) {
    composable(Route.AssessmentIntro.route) {
        AssessmentIntroScreen(
            onBack = { navController.popBackStack() },
            onStart = { navController.navigate(Route.Assessment.route) }
        )
    }
    composable(Route.Assessment.route) {
        AssessmentScreen(
            onBack = { navController.popBackStack() },
            onFinished = {
                navController.navigate(Route.AssessmentResult.route) {
                    // 做题页与引导页都不必留在返回栈里。
                    popUpTo(Route.AssessmentIntro.route) { inclusive = true }
                }
            }
        )
    }
    composable(Route.AssessmentResult.route) {
        AssessmentResultScreen(
            onBack = { navController.popBackStack() },
            onDone = { navController.navigateToTab(Route.Me.route) }
        )
    }
    composable(Route.ExpressionLibrary.route) {
        ExpressionLibraryScreen(onBack = { navController.popBackStack() })
    }
}
