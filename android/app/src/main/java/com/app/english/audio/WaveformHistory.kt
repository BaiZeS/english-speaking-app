package com.app.english.audio

/**
 * Fixed-capacity sliding window of recent mic levels, sized to be rendered as a
 * scrolling waveform: the newest sample lands on the right and every earlier
 * sample shifts one slot left, so the strip reads as time flowing backwards off
 * the left edge.
 *
 * Why the buffer lives here rather than in the composable: the recorder is the
 * only thing that knows when a take starts, ends, or is thrown away, and a
 * composable-local `remember` buffer is silently discarded whenever its host
 * screen recomposes out of a navigation transition — which is exactly when the
 * user is still looking at the shape of the take they just finished.
 *
 * Pure Kotlin (no Android, no coroutines) so its ordering and padding rules are
 * pinned by [WaveformHistoryTest] the same way [AudioLevelMapping] is.
 */
class WaveformHistory(val capacity: Int) {

    init {
        require(capacity > 0) { "capacity must be positive, was $capacity" }
    }

    private val samples = FloatArray(capacity)

    /** Slot the next sample overwrites; wraps at [capacity]. */
    private var writeIndex = 0

    /** How many slots hold real samples so far (never exceeds [capacity]). */
    private var filled = 0

    /**
     * Append one level, clamped to 0..1 (the recorder hands over a dBFS-mapped
     * value, but a caller passing garbage must not be able to draw off-scale
     * bars). Once full, the oldest sample is dropped.
     */
    fun push(level: Float) {
        samples[writeIndex] = level.coerceIn(0f, 1f)
        writeIndex = (writeIndex + 1) % capacity
        if (filled < capacity) filled++
    }

    /**
     * The window in display order: oldest first, newest last. Until the strip
     * has been filled the result is zero-padded on the **left**, so a waveform
     * grows in from the right edge instead of the bars sliding in from the left.
     */
    fun snapshot(): FloatArray {
        val out = FloatArray(capacity)
        val start = writeIndex - filled
        for (i in 0 until filled) {
            out[capacity - filled + i] = samples[((start + i) % capacity + capacity) % capacity]
        }
        return out
    }

    /** Number of real samples currently held (<= [capacity]). */
    val size: Int get() = filled

    fun clear() {
        writeIndex = 0
        filled = 0
    }

    companion object {
        /**
         * Default window width in bars. The recorder emits one sample per 40 ms
         * frame (~25 Hz), so 40 bars is ~1.6 s of history — long enough to hold a
         * whole practice sentence, short enough that each bar stays visually
         * separable on a phone-width row.
         */
        const val DEFAULT_CAPACITY = 40
    }
}
