package com.app.english.data.remote

import org.junit.Assert.assertEquals
import org.junit.Test

/**
 * Round-trip tests for the new /books and /dialogue/scenes payloads. The
 * server emits snake_case + Chinese metadata; the Android client has to
 * decode them faithfully and pass them through to the picker UI.
 */
class BooksDtoMappingTest {
    private val json = kotlinx.serialization.json.Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
    }

    @Test
    fun booksResponse_decodesCuratedCatalog() {
        val payload = """
            {
              "books": [
                {"id":"nce1","display_name":"新概念英语 第一册","description":"入门","level":"beginner","lesson_count":1},
                {"id":"nce2","display_name":"新概念英语 第二册","description":"进阶","level":"intermediate","lesson_count":2}
              ],
              "default_book":"nce1"
            }
        """.trimIndent()
        val dto = json.decodeFromString(BooksResponseDto.serializer(), payload)
        assertEquals(2, dto.books.size)
        assertEquals("新概念英语 第一册", dto.books[0].displayName)
        assertEquals(1, dto.books[0].lessonCount)
        assertEquals("nce1", dto.defaultBook)
    }

    @Test
    fun booksResponse_emptyArrayStillYieldsDefault() {
        val payload = """{"books":[],"default_book":""}"""
        val dto = json.decodeFromString(BooksResponseDto.serializer(), payload)
        assertEquals(0, dto.books.size)
        assertEquals("", dto.defaultBook)
    }

    @Test
    fun dialogueScenesResponse_keepsAllSceneFields() {
        val payload = """
            {
              "scenes": [
                {"id":"daily_conversation","title":"日常寒暄","description":"聊聊今天"},
                {"id":"job_interview","title":"求职面试","description":"模拟面试"}
              ],
              "default_scene":"daily_conversation"
            }
        """.trimIndent()
        val dto = json.decodeFromString(DialogueScenesResponseDto.serializer(), payload)
        assertEquals(2, dto.scenes.size)
        assertEquals("日常寒暄", dto.scenes[0].title)
        assertEquals("daily_conversation", dto.defaultScene)
    }

    @Test
    fun statsResponse_handlesZeroStateGracefully() {
        // No history rows for this device — server returns all-zero payload.
        val payload = """
            {
              "total_sessions":0,
              "avg_total":0.0,
              "avg_pronunciation":0.0,
              "avg_fluency":0.0,
              "avg_completeness":0.0,
              "best_total":0.0,
              "recent_sessions":0,
              "streak_days":0,
              "daily":[],
              "lessons_attempted":[]
            }
        """.trimIndent()
        val dto = json.decodeFromString(StatsResponseDto.serializer(), payload)
        assertEquals(0, dto.totalSessions)
        assertEquals(0, dto.streakDays)
        assertEquals(emptyList<String>(), dto.lessonsAttempted)
    }

    @Test
    fun statsResponse_decodesDailyBuckets() {
        val payload = """
            {
              "total_sessions":5,
              "avg_total":82.0,
              "avg_pronunciation":85.0,
              "avg_fluency":80.0,
              "avg_completeness":81.0,
              "best_total":92.0,
              "recent_sessions":2,
              "streak_days":3,
              "daily":[
                {"date":"2026-07-18","avg_total":80.0,"avg_pronunciation":82.0,"avg_fluency":78.0,"avg_completeness":79.0,"sessions":2},
                {"date":"2026-07-19","avg_total":85.0,"avg_pronunciation":88.0,"avg_fluency":82.0,"avg_completeness":84.0,"sessions":3}
              ],
              "lessons_attempted":[1,2,3]
            }
        """.trimIndent()
        val dto = json.decodeFromString(StatsResponseDto.serializer(), payload)
        assertEquals(2, dto.daily.size)
        assertEquals(80.0, dto.daily[0].avgTotal, 0.001)
        assertEquals(3, dto.daily[1].sessions)
        assertEquals(listOf(1, 2, 3), dto.lessonsAttempted)
    }

    @Test
    fun lessonProgressDto_decodesAllFields() {
        val payload = """
            {
              "lesson_id": 1,
              "attempt_count": 4,
              "best_score": 92.0,
              "last_score": 78.0,
              "last_practiced_at": "2026-07-21T03:14:00+00:00"
            }
        """.trimIndent()
        val dto = json.decodeFromString(LessonProgressDto.serializer(), payload)
        assertEquals(1, dto.lessonId)
        assertEquals(4, dto.attemptCount)
        assertEquals(92.0, dto.bestScore, 0.001)
        assertEquals(78.0, dto.lastScore, 0.001)
        assertEquals("2026-07-21T03:14:00+00:00", dto.lastPracticedAt)
    }

    @Test
    fun lessonProgressDto_handlesNullTimestamp() {
        val payload = """
            {
              "lesson_id": 2,
              "attempt_count": 0,
              "best_score": 0.0,
              "last_score": 0.0,
              "last_practiced_at": null
            }
        """.trimIndent()
        val dto = json.decodeFromString(LessonProgressDto.serializer(), payload)
        assertEquals(0, dto.attemptCount)
        assertEquals(null, dto.lastPracticedAt)
    }
}
