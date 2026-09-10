package com.app.english.audio

import com.app.english.audio.RecordingTakeClock.WARNING_REMAINING_MS
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class RecordingTakeClockTest {

    private val t0 = 1_000_000L

    @Test
    fun formatElapsed_readsAsClockNotRawMillis() {
        assertEquals("0:00", RecordingTakeClock.formatElapsed(0L))
        assertEquals("0:07", RecordingTakeClock.formatElapsed(7_000L))
        assertEquals("1:05", RecordingTakeClock.formatElapsed(65_000L))
    }

    @Test
    fun formatElapsed_truncatesSubSecondRemainder() {
        // A take that has not crossed the next second yet must not run ahead of itself.
        assertEquals("0:09", RecordingTakeClock.formatElapsed(9_999L))
        assertEquals("0:10", RecordingTakeClock.formatElapsed(10_000L))
    }

    @Test
    fun formatElapsed_keepsCountingPastOneMinute() {
        assertEquals("1:59", RecordingTakeClock.formatElapsed(119_000L))
        assertEquals("2:00", RecordingTakeClock.formatElapsed(120_000L))
        assertEquals("12:34", RecordingTakeClock.formatElapsed(754_000L))
    }

    @Test
    fun elapsedMs_neverGoesNegativeOnClockSkew() {
        assertEquals(0L, RecordingTakeClock.elapsedMs(t0, t0 - 25_000L))
        assertEquals(4_000L, RecordingTakeClock.elapsedMs(t0, t0 + 4_000L))
    }

    @Test
    fun nearCap_opensExactlyFiveSecondsBeforeTheDeadline() {
        val cap = 30_000L
        assertFalse(RecordingTakeClock.isNearCap(cap - WARNING_REMAINING_MS - 1, cap))
        assertTrue(RecordingTakeClock.isNearCap(cap - WARNING_REMAINING_MS, cap))
        assertTrue(RecordingTakeClock.isNearCap(cap, cap))
    }

    @Test
    fun nearCap_isNeverTrueForAnUnlimitedTake() {
        // Shadow mode records without a cap; promising an auto-send it cannot
        // honour is exactly the copy defect this release is removing.
        assertFalse(RecordingTakeClock.isNearCap(29_000L, null))
        assertFalse(RecordingTakeClock.isNearCap(9_999_000L, null))
        assertFalse(RecordingTakeClock.isNearCap(9_999_000L, 0L))
        assertFalse(RecordingTakeClock.isNearCap(9_999_000L, -1L))
    }

    @Test
    fun label_showsPlainElapsedWhileThereIsTimeLeft() {
        assertEquals(
            "0:07",
            RecordingTakeClock.takeElapsedLabel(t0, t0 + 7_000L, AudioRecorder.MAX_TAKE_MS)
        )
    }

    @Test
    fun label_warnsInTheAutoSendWindow() {
        val cap = AudioRecorder.MAX_TAKE_MS
        assertEquals(
            "0:26 · 即将自动发送",
            RecordingTakeClock.takeElapsedLabel(t0, t0 + 26_000L, cap)
        )
    }

    @Test
    fun label_omitsTheCapWarningForShadowMode() {
        assertEquals(
            "1:12",
            RecordingTakeClock.takeElapsedLabel(t0, t0 + 72_000L, null)
        )
    }

    @Test
    fun capHint_namesTheRealDeadlineAndStaysSilentWhenThereIsNone() {
        assertEquals("30 秒后自动发送", RecordingTakeClock.capHint(AudioRecorder.MAX_TAKE_MS))
        assertNull(RecordingTakeClock.capHint(null))
        assertNull(RecordingTakeClock.capHint(0L))
    }

    @Test
    fun capHint_roundsUpForANonWholeSecondCap() {
        // Never state a deadline shorter than the recorder will actually allow.
        assertEquals("11 秒内自动发送", RecordingTakeClock.capHint(10_500L))
    }
}
