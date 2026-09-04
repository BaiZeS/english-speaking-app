package com.app.english.ui.navigation

import com.app.english.ui.player.PlayerMode

/**
 * 导航目的地清单(v2.0 重构, 计划 §6.3)。
 *
 * 底部 4 Tab: 首页 / 课程 / 词汇 / 我的。v1 的屏幕一个都不删, 只是搬进对应的
 * hub: 课文列表 -> 课程 Tab 的「课本」分段, 历史 / 设置 / 关于 -> 我的,
 * 弱词训练 -> 词汇 Tab。练习链路(player / free_dialogue / score_result)的参数
 * 语义与 v1.4 完全一致。
 */
sealed class Route(val route: String) {
    // ---- 底部 Tab ----
    data object Home : Route("home")
    data object Courses : Route("courses")
    data object Vocab : Route("vocab")
    data object Me : Route("me")

    // ---- 课本(v1 平移, 挂在课程 Tab 下) ----
    data object LessonDetail : Route("lesson/{book}/{lessonId}") {
        const val ARG_BOOK = "book"
        const val ARG_LESSON_ID = "lessonId"
        fun create(book: String, lessonId: Int): String = "lesson/$book/$lessonId"
    }

    data object Player : Route("player/{book}/{lessonId}/{mode}/{roleName}") {
        const val ARG_BOOK = "book"
        const val ARG_LESSON_ID = "lessonId"
        const val ARG_MODE = "mode"
        const val ARG_ROLE_NAME = "roleName"
        const val NO_ROLE = "_"

        fun create(
            book: String,
            lessonId: Int,
            mode: PlayerMode,
            roleName: String? = null
        ): String = "player/$book/$lessonId/${mode.wire}/${roleName ?: NO_ROLE}"
    }

    data object FreeDialogue : Route("free_dialogue/{book}/{lessonId}") {
        const val ARG_BOOK = "book"
        const val ARG_LESSON_ID = "lessonId"
        fun create(book: String, lessonId: Int): String = "free_dialogue/$book/$lessonId"
    }

    data object ScoreResult : Route("score_result")

    // ---- 情景课(P6 全流程: 详情 -> 打基础 -> 实战 -> 复盘) ----
    data object SceneDetail : Route("scene_detail/{sceneId}") {
        const val ARG_SCENE_ID = "sceneId"
        fun create(sceneId: String): String = "scene_detail/$sceneId"
    }

    /** 打基础; 会话 id 是服务端状态机的句柄, 快照经 GET /sessions/{id} 恢复。 */
    data object SceneBriefing : Route("scene_briefing/{sessionId}") {
        const val ARG_SESSION_ID = "sessionId"
        fun create(sessionId: String): String = "scene_briefing/$sessionId"
    }

    data object SceneMission : Route("scene_mission/{sessionId}") {
        const val ARG_SESSION_ID = "sessionId"
        fun create(sessionId: String): String = "scene_mission/$sessionId"
    }

    data object SceneReview : Route("scene_review/{sessionId}") {
        const val ARG_SESSION_ID = "sessionId"
        fun create(sessionId: String): String = "scene_review/$sessionId"
    }

    // ---- 我的 / 词汇 的二级页 ----
    data object History : Route("history")
    data object HistoryDetail : Route("history_detail")
    data object MistakeDrill : Route("mistake_drill")
    data object Settings : Route("settings")
    data object About : Route("about")

    // ---- 占位目的地(P5 建, P6/P7 填) ----
    data object GenerateCourse : Route("generate_course")
    data object AssessmentIntro : Route("assessment_intro")
    data object ExpressionLibrary : Route("expressions")
}

/**
 * 导航图上应当存在的全部目的地。
 *
 * 这张清单是给「静态导航审查」用的(`AppTabsTest`): v2.0 重构是**搬家**而不是删房间,
 * v1 的每一个 route 都必须还在图里, P6/P7 再往上添。
 */
val allRoutes: List<Route> = listOf(
    Route.Home,
    Route.Courses,
    Route.Vocab,
    Route.Me,
    Route.LessonDetail,
    Route.Player,
    Route.FreeDialogue,
    Route.ScoreResult,
    Route.SceneDetail,
    Route.SceneBriefing,
    Route.SceneMission,
    Route.SceneReview,
    Route.History,
    Route.HistoryDetail,
    Route.MistakeDrill,
    Route.Settings,
    Route.About,
    Route.GenerateCourse,
    Route.AssessmentIntro,
    Route.ExpressionLibrary
)
