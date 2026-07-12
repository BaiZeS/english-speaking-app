package com.app.english.audio

import android.content.Context
import androidx.media3.common.MediaItem
import androidx.media3.common.PlaybackException
import androidx.media3.common.Player
import androidx.media3.exoplayer.ExoPlayer
import timber.log.Timber

/**
 * Plays a remote audio URL (the /tts audio_url) via Media3 ExoPlayer.
 * Caller releases the instance when done.
 */
class AudioPlayer(context: Context) {
    private val player: ExoPlayer = ExoPlayer.Builder(context).build()
    private var completionCallback: () -> Unit = {}

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
        completionCallback = onCompletion
        player.setMediaItem(MediaItem.fromUri(url))
        player.prepare()
        player.playWhenReady = true
    }

    fun stop() {
        player.stop()
        player.clearMediaItems()
    }

    fun release() {
        player.removeListener(listener)
        player.release()
    }
}
