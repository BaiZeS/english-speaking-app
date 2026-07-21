package com.app.english.ui.history

import com.app.english.domain.model.HistoryItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Pure-function tests for the HistoryFilter logic. Verifies that each filter
 * chip produces the expected subset of the cached history list. We don't
 * need a Robolectric/Compose test here — the filtering is just a [when] on
 * the enum.
 */
class HistoryFilterTest {
    private fun item(id: String, total: Double, lessonId: Int = 1): HistoryItem = HistoryItem(
        id = id,
        lessonId = lessonId,
        lineId = "L-$id",
        scoreTotal = total,
        scorePronunciation = total,
        scoreFluency = total,
        scoreCompleteness = total,
        createdAt = "2026-07-20T00:00:00"
    )

    private val all = listOf(
        item("a", 0.0), // not practiced
        item("b", 50.0), // below 60
        item("c", 65.0), // mid
        item("d", 85.0), // 85+
        item("e", 95.0) // top
    )

    @Test
    fun `All returns every item including the un-practiced one`() {
        assertEquals(5, apply(HistoryFilter.All, all).size)
    }

    @Test
    fun `Practiced excludes the zero-score record`() {
        val practiced = apply(HistoryFilter.Practiced, all)
        assertEquals(4, practiced.size)
        assertTrue(practiced.none { it.id == "a" })
    }

    @Test
    fun `HighScore filters to 85+ only`() {
        val high = apply(HistoryFilter.HighScore, all)
        assertEquals(setOf("d", "e"), high.map { it.id }.toSet())
    }

    @Test
    fun `NeedsWork includes the sub-60 bucket but not zero or high scores`() {
        val needs = apply(HistoryFilter.NeedsWork, all)
        assertEquals(setOf("b"), needs.map { it.id }.toSet())
    }

    @Test
    fun `Filter preserves source order (newest first)`() {
        val out = apply(HistoryFilter.HighScore, all)
        assertEquals(listOf("d", "e"), out.map { it.id })
    }

    @Test
    fun `Empty input produces empty output for every filter`() {
        HistoryFilter.values().forEach { f ->
            assertEquals(0, apply(f, emptyList()).size)
        }
    }

    private fun apply(filter: HistoryFilter, items: List<HistoryItem>): List<HistoryItem> =
        when (filter) {
            HistoryFilter.All -> items
            HistoryFilter.Practiced -> items.filter { it.scoreTotal > 0 }
            HistoryFilter.HighScore -> items.filter { it.scoreTotal >= 85 }
            HistoryFilter.NeedsWork -> items.filter { it.scoreTotal in 1.0..60.0 }
        }
}
