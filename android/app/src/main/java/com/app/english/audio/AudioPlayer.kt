package com.app.english.audio

import android.content.Context
import android.os.Handler
import android.os.Looper
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import timber.log.Timber

/**
 * Plays a remote audio URL (the /tts audio_url) via Media3 ExoPlayer.
 * Caller releases the instance when done.
 *
 * All methods must be called on the main thread (ExoPlayer is bound to the
 * thread that created it, and the sequence chaining posts to the main looper).
 */
class AudioPlayer(context: Context) {
    private val player: ExoPlayer = ExoPlayer.Builder(context).build()
    private var completionCallback: () -> Unit = {}
    private val handler = Handler(Looper.getMainLooper())

    private val listener = object : Player.Listener {
        override fun onPlaybackStateChanged(state: Int) {
            if (state == Player.STATE_ENDED) {
                completionCallback()
            }
        }

        override fun onPlayerError(error: PlaybackException) {
            Timber.e(error, "ExoPlayer playback error")
            completionCallback()
        }
    }

    init {
        player.addListener(listener)
    }

    fun play(url: String, onCompletion: () -> Unit = {}) {
        cancelPendingSequence()
        completionCallback = onCompletion
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        player.playWhenReady = true
    }

    /**
     * Plays [items] one after another, waiting [gapMs] between the end of one
     * item and the start of the next. [onIndex] reports the item that is
     * starting; [onComplete] fires after the last item finishes. Implemented
     * on top of single-item [play] plus a delayed chain on the main looper,
     * because ExoPlayer playlist gap control is unreliable for remote URLs.
     * [stop]/[release] cancel any pending continuation.
     */
    fun playSequence(
        items: List<String>,
        gapMs: Long,
        onIndex: (Int) -> Unit = {},
        onComplete: () -> Unit = {}
    ) {
        cancelPendingSequence()
        if (items.isEmpty()) {
            onComplete()
            return
        }
        playSequenceItem(items, gapMs, 0, onIndex, onComplete)
    }

    private fun playSequenceItem(
        items: List<String>,
        gapMs: Long,
        index: Int,
        onIndex: (Int) -> Unit,
        onComplete: () -> Unit
    ) {
        onIndex(index)
        val isLast = index == items.lastIndex
        play(items[index]) {
            if (isLast) {
                onComplete()
            } else {
                handler.postDelayed(
                    {
                        playSequenceItem(items, gapMs, index + 1, onIndex, onComplete)
                    },
                    gapMs
                )
            }
        }
    }

    fun stop() {
        cancelPendingSequence()
        player.stop()
        player.clearMediaItems()
    }

    fun release() {
        cancelPendingSequence()
        player.removeListener(listener)
        player.release()
    }

    /** Drops any not-yet-fired "play next item" continuation. */
    private fun cancelPendingSequence() {
        handler.removeCallbacksAndMessages(null)
    }
}
