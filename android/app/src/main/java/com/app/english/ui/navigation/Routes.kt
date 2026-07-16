package com.app.english.ui.navigation

sealed class Route(val route: String) {
    data object Lessons : Route("lessons")

    data object LessonDetail : Route("lesson/{lessonId}") {
        const val ARG_LESSON_ID = "lessonId"
        fun create(lessonId: Int): String = "lesson/$lessonId"
    }

    data object Player : Route("player/{lessonId}/{mode}/{roleName}") {
        const val ARG_LESSON_ID = "lessonId"
        const val ARG_MODE = "mode"
        const val ARG_ROLE_NAME = "roleName"
        // "_" is the wire-format placeholder for "no role" (read-along mode).
        // Path-based so deep links survive, query-based would be too noisy.
        const val NO_ROLE = "_"
        fun create(
            lessonId: Int,
            mode: com.app.english.ui.player.PlayerMode,
            roleName: String? = null
        ): String = "player/$lessonId/${mode.wire}/${roleName ?: NO_ROLE}"
    }

    data object ScoreResult : Route("score_result")

    data object History : Route("history")

    data object HistoryDetail : Route("history_detail")

    data object Settings : Route("settings")
}

val topLevelRoutes = setOf(Route.Lessons.route, Route.History.route, Route.Settings.route)
