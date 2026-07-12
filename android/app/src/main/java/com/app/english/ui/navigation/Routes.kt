package com.app.english.ui.navigation

sealed class Route(val route: String) {
    data object Lessons : Route("lessons")

    data object LessonDetail : Route("lesson/{lessonId}") {
        const val ARG_LESSON_ID = "lessonId"
        fun create(lessonId: Int): String = "lesson/$lessonId"
    }

    data object Player : Route("player/{lessonId}/{roleName}") {
        const val ARG_LESSON_ID = "lessonId"
        const val ARG_ROLE_NAME = "roleName"
        fun create(lessonId: Int, roleName: String): String = "player/$lessonId/$roleName"
    }

    data object ScoreResult : Route("score_result")

    data object History : Route("history")

    data object HistoryDetail : Route("history_detail")

    data object Settings : Route("settings")
}

val topLevelRoutes = setOf(Route.Lessons.route, Route.History.route, Route.Settings.route)
