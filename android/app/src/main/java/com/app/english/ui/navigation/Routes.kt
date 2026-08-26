package com.app.english.ui.navigation

import com.app.english.ui.player.PlayerMode

sealed class Route(val route: String) {
    data object Lessons : Route("lessons")

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
    data object History : Route("history")
    data object HistoryDetail : Route("history_detail")
    data object Dashboard : Route("dashboard")
    data object MistakeDrill : Route("mistake_drill")
    data object Settings : Route("settings")
    data object About : Route("about")
}

val topLevelRoutes = setOf(
    Route.Dashboard.route,
    Route.Lessons.route,
    Route.History.route,
    Route.Settings.route
)
