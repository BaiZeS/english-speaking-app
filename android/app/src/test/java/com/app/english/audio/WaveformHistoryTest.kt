package com.app.english.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Assert.assertTrue
import org.junit.Test

class WaveformHistoryTest {

    @Test
    fun emptySnapshot_isAllZeros() {
        val history = WaveformHistory(4)
        assertEquals(listOf(0f, 0f, 0f, 0f), history.snapshot().toList())
        assertEquals(0, history.size)
    }

    @Test
    fun partialWindow_padsOnTheLeftSoBarsGrowInFromTheRight() {
        val history = WaveformHistory(4)
        history.push(0.6f)
        history.push(0.8f)
        // Oldest first, newest last, empty slots leading.
        assertEquals(listOf(0f, 0f, 0.6f, 0.8f), history.snapshot().toList())
        assertEquals(2, history.size)
    }

    @Test
    fun fullWindow_shiftsLeft_newestOnTheRight() {
        val history = WaveformHistory(3)
        listOf(0.1f, 0.2f, 0.3f).forEach(history::push)
        assertEquals(listOf(0.1f, 0.2f, 0.3f), history.snapshot().toList())
        history.push(0.4f)
        assertEquals(listOf(0.2f, 0.3f, 0.4f), history.snapshot().toList())
    }

    @Test
    fun overflow_dropsOnlyTheOldest() {
        val history = WaveformHistory(3)
        (1..10).forEach { history.push(it / 100f) }
        assertEquals(3, history.size)
        assertEquals(listOf(0.08f, 0.09f, 0.10f), history.snapshot().toList())
    }

    @Test
    fun ringWrap_keepsChronologicalOrder() {
        // Push exactly one full lap plus a bit; ordering must survive the wrap.
        // Halves of 16 so every level is both in 0..1 and exact in binary float.
        val history = WaveformHistory(4)
        (1..9).forEach { history.push(it / 16f) }
        assertEquals((6..9).map { it / 16f }, history.snapshot().toList())
    }

    @Test
    fun push_clampsInputToUnitRange() {
        val history = WaveformHistory(2)
        history.push(1.7f)
        history.push(-3f)
        assertEquals(listOf(1f, 0f), history.snapshot().toList())
    }

    @Test
    fun clear_emptiesTheStripButKeepsCapacity() {
        val history = WaveformHistory(3)
        listOf(0.5f, 0.5f, 0.5f).forEach(history::push)
        history.clear()
        assertEquals(0, history.size)
        assertEquals(listOf(0f, 0f, 0f), history.snapshot().toList())
        history.push(0.9f)
        assertEquals(listOf(0f, 0f, 0.9f), history.snapshot().toList())
    }

    @Test
    fun capacityOne_holdsJustTheLatestSample() {
        val history = WaveformHistory(1)
        history.push(0.2f)
        history.push(0.7f)
        assertEquals(listOf(0.7f), history.snapshot().toList())
    }

    @Test
    fun nonPositiveCapacity_isRejected() {
        assertThrows(IllegalArgumentException::class.java) { WaveformHistory(0) }
        assertThrows(IllegalArgumentException::class.java) { WaveformHistory(-1) }
    }

    @Test
    fun defaultCapacity_coversAboutOnePracticeSentence() {
        // Recorder emits one sample per 40 ms frame; 40 bars ~= 1.6 s of history.
        val secondsVisible = WaveformHistory.DEFAULT_CAPACITY * 0.04
        assertTrue("default window must cover a full sentence", secondsVisible >= 1.0)
        assertTrue("default window must stay readable on a phone row", secondsVisible <= 2.5)
    }
}
