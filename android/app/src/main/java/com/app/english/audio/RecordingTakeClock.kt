package com.app.english.audio

/**
 * Pure time arithmetic for a live recording take, so the tap-toggle surfaces can
 * show honest elapsed time instead of leaving the user guessing whether the mic
 * is still hot.
 *
 * These surfaces keep a tap-to-start / tap-to-stop gesture (a 30 s shadow or
 * free-dialogue take is far too long to hold a button for), and the gesture that
 * actually ships is the thing the copy used to contradict. Showing elapsed time
 * is what makes "tap again to stop" legible: without it a held take looks
 * identical to a dead button.
 *
 * Pure Kotlin with injected `nowMs` — no `System.currentTimeMillis()` inside —
 * so the countdown boundary cases are pinned by [RecordingTakeClockTest].
 */
object RecordingTakeClock {

    /**
     * How close to the auto-send cap counts as "about to fire". Matches the
     * recorder's own auto-stop, which finalizes the take at `maxDurationMs`
     * without waiting for the user (see [AudioRecorder.MAX_TAKE_MS]).
     */
    const val WARNING_REMAINING_MS = 5_000L

    private const val SECOND_MS = 1000L
    private const val MINUTE_MS = 60 * SECOND_MS

    /** Wall-clock elapsed since the take began, never negative (clock skew safe). */
    fun elapsedMs(startedAtMs: Long, nowMs: Long): Long = (nowMs - startedAtMs).coerceAtLeast(0L)

    /**
     * `m:ss` — minutes deliberately left unbounded (not rolled over at 60) so a
     * cap-less shadow take keeps reading correctly past a minute.
     */
    fun formatElapsed(elapsedMs: Long): String {
        val totalSeconds = elapsedMs / SECOND_MS
        val minutes = totalSeconds / 60
        val seconds = totalSeconds % 60
        return "%d:%02d".format(minutes, seconds)
    }

    /**
     * True once the take is within [WARNING_REMAINING_MS] of its cap, so the UI
     * can tint the timer before the take sends itself out from under the user.
     * A null cap means unlimited (shadow mode) and can never be "near".
     */
    fun isNearCap(elapsedMs: Long, maxDurationMs: Long?): Boolean {
        if (maxDurationMs == null || maxDurationMs <= 0L) return false
        return elapsedMs >= maxDurationMs - WARNING_REMAINING_MS
    }

    /**
     * Cap reminder for the idle state, e.g. "30 秒后自动发送"; null when the take
     * is unlimited, because there is then no promise to make.
     */
    fun capHint(maxDurationMs: Long?): String? {
        if (maxDurationMs == null || maxDurationMs <= 0L) return null
        val seconds = maxDurationMs / SECOND_MS
        return if (seconds * SECOND_MS == maxDurationMs) {
            "$seconds 秒后自动发送"
        } else {
            "${(seconds + 1)} 秒内自动发送"
        }
    }

    /**
     * Live label for a take in progress: elapsed time, plus a warning tail once
     * the auto-send window opens.
     */
    fun takeElapsedLabel(startedAtMs: Long, nowMs: Long, maxDurationMs: Long?): String {
        val elapsed = elapsedMs(startedAtMs, nowMs)
        val base = formatElapsed(elapsed)
        return if (isNearCap(elapsed, maxDurationMs)) "$base · 即将自动发送" else base
    }
}
