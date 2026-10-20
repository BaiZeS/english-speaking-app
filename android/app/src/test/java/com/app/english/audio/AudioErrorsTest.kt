package com.app.english.audio

import org.junit.Assert.assertNotEquals
import org.junit.Test

class AudioErrorsTest {
    // media3: PlaybackException.ERROR_CODE_AUDIO_TRACK_INIT_FAILED
    private val audioTrackInitFailed = 5001
    private val audioTrackWriteFailed = 5002
    private val ioNetworkFailed = 2001
    private val ioFileNotFound = 2005
    private val ioCleartext = 2007
    private val parsingUnsupported = 3003
    private val unspecified = 1000

    @Test
    fun `audio track failure names the real cause and keeps the code`() {
        val msg = audioPlaybackErrorMessage(audioTrackInitFailed)
        assert(msg.contains("设备"))
        assert(msg.contains("5001"))
        assert(audioPlaybackErrorMessage(audioTrackWriteFailed).contains("5002"))
    }

    @Test
    fun `network and http failures read as connectivity problems`() {
        val network = audioPlaybackErrorMessage(ioNetworkFailed)
        assert(network.contains("服务器"))
        assert(network.contains("2001"))
        assert(audioPlaybackErrorMessage(ioFileNotFound).contains("2005"))
        assert(audioPlaybackErrorMessage(ioCleartext).contains("2007"))
    }

    @Test
    fun `container failure is told apart from network failure`() {
        assertNotEquals(
            audioPlaybackErrorMessage(parsingUnsupported),
            audioPlaybackErrorMessage(ioNetworkFailed)
        )
        assert(audioPlaybackErrorMessage(parsingUnsupported).contains("3003"))
    }

    @Test
    fun `unknown code still tells the user to report it`() {
        assert(audioPlaybackErrorMessage(unspecified).contains("1000"))
    }
}
