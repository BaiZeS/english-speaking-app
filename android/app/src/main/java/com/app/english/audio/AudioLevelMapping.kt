package com.app.english.audio

import kotlin.math.log10

/**
 * Maps a raw 16-bit PCM peak (0..32767) to a normalized 0..1 meter level and
 * smooths the frame-to-frame jumps so the VU meter reads like waveform instead
 * of a flickering number.
 *
 * Reason for the log mapping: a peak-linear scale (peak/32767) buries normal
 * speech — spoken input at 20-30cm peaks around 3k-12k, i.e. 0.09-0.37 — so a
 * threshold meter would light only a fraction of the bars and barely move.
 * dBFS puts the same speech in the 0.5-0.95 range where the meter is lively.
 */
object AudioLevelMapping {
    /** dBFS value that maps to level 0. Anything quieter (incl. silence) is 0. */
    const val FLOOR_DB = -50f

    /** Span from [FLOOR_DB] to the value that maps to level 1 (FLOOR_DB + SPAN_DB ~= -6 dBFS). */
    const val SPAN_DB = 44f

    private const val FULL_SCALE = 32767f

    /**
     * Peak abs sample -> 0..1 level on a dBFS scale. [peak] <= 0 (silence) maps
     * to 0; the result is clamped to 0..1.
     */
    fun peakToLevel(peak: Int): Float {
        if (peak <= 0) return 0f
        val dbFs = 20f * log10(peak / FULL_SCALE)
        return ((dbFs - FLOOR_DB) / SPAN_DB).coerceIn(0f, 1f)
    }

    /**
     * One-pole smoothing with a faster attack than decay: rising levels snap up
     * (~2 frames / 80ms to close most of the gap) so speech onset is visible
     * immediately, falling levels ease down (~4 frames) so the meter decays
     * instead of stuttering to zero on tiny gaps. Both factors keep the result
     * within the prev..target range (no overshoot).
     */
    fun smooth(prev: Float, target: Float): Float =
        prev + (target - prev) * if (target > prev) ATTACK else DECAY

    private const val ATTACK = 0.7f
    private const val DECAY = 0.25f
}
