package com.app.english.ui.lessons

import com.app.english.domain.model.LessonSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class LessonListFilterTest {
    private fun lesson(id: Int, no: Int, title: String): LessonSummary = LessonSummary(
        id = id,
        book = "nce1",
        lessonNo = no,
        title = title,
        roleCount = 2,
        durationS = 30.0
    )

    private val all = listOf(
        lesson(1, 1, "A Private Conversation"),
        lesson(2, 2, "Breakfast or Lunch?"),
        lesson(3, 3, "Please Send Me a Card"),
        lesson(4, 4, "An Exciting Trip"),
        lesson(5, 5, "No Wrong Answers")
    )

    private fun search(q: String, lessons: List<LessonSummary> = all): List<LessonSummary> {
        if (q.isBlank()) return lessons
        val needle = q.trim().lowercase()
        return lessons.filter {
            it.title.lowercase().contains(needle) || "lesson ${it.lessonNo}".contains(needle)
        }
    }

    @Test
    fun emptyQueryReturnsEverything() {
        assertEquals(5, search("").size)
        assertEquals(5, search("   ").size)
    }

    @Test
    fun matchesByTitleText() {
        val out = search("breakfast")
        assertEquals(listOf(2), out.map { it.id })
    }

    @Test
    fun caseInsensitive() {
        val out = search("CARD")
        assertEquals(listOf(3), out.map { it.id })
    }

    @Test
    fun matchesByLessonNumberPrefix() {
        val out = search("lesson 1")
        assertEquals(listOf(1), out.map { it.id })
    }

    @Test
    fun partialSubstringWorksInsideWord() {
        val out = search("pri")
        assertEquals(listOf(1), out.map { it.id })
    }

    @Test
    fun noMatchReturnsEmptyList() {
        val out = search("nonexistent-keyword")
        assertTrue(out.isEmpty())
    }

    @Test
    fun whitespaceOnlyTreatedAsEmpty() {
        assertEquals(5, search("\t\n  ").size)
    }
}
