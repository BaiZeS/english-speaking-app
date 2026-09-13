package com.app.english.audio

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.os.Build
import android.os.SystemClock
import java.io.File
import java.io.FileOutputStream
import kotlin.math.abs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import timber.log.Timber

/**
 * Records microphone audio to a raw PCM file (L16, 16kHz, mono) via [AudioRecord].
 *
 * PCM L16 16kHz mono is exactly what the Xunfei ISE speech-evaluation backend expects,
 * so the recorded bytes are uploaded as-is (no transcoding). Caller owns the lifecycle:
 * [start] then [stop] (or [cancel]).
 *
 * While recording, [levelFlow] emits smoothed, dBFS-normalized amplitude values
 * (0..1) one 640-sample frame (40ms, i.e. 25Hz) at a time: an attack/decay
 * envelope meant for a VU-style reading, resetting to 0 once the read loop exits.
 * Values derive from the peak absolute PCM sample per frame and are never
 * persisted. See [AudioLevelMapping] for scaling. Since v2.2.1 this envelope is
 * THE feed for the on-screen recording bar (the live volume pulse meter, see
 * com.app.english.ui.components.RecordingPulseMeter); the frozen "last take"
 * look is that component's own peak capture, so the recorder keeps no display
 * history.
 *
 * Threading / lifecycle:
 *  - [start]/[stop] do their AudioRecord work on [Dispatchers.IO] and are suspend, so no
 *    click handler blocks the main thread on mic init anymore.
 *  - A busy gate inside [start] rejects concurrent starts, so ViewModel double-tap races
 *    can no longer leak a second AudioRecord holding the mic.
 *  - The read loop owns stop/release of its AudioRecord, exactly once per take
 *    (state-guarded). [stop] merely requests the end and awaits the loop; [cancel] marks
 *    the take for deletion. A 30s cap auto-finalizes and drives [onAutoStop], and a later
 *    user stop is an idempotent hand-back of the same file - never a double release.
 *
 * Injected as a singleton (see AudioModule) so the busy gate and level flow are global:
 * one screen's live take makes another's start fail fast with a clear error instead of
 * fighting over the mic.
 */
class AudioRecorder(private val context: Context) {

    private enum class State { IDLE, RECORDING, FINISHED }

    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private val lock = Any()

    private var state: State = State.IDLE
    private var session: RecordingSession? = null
    private var sessionCancelled: Boolean = false

    private var recorder: AudioRecord? = null
    private var echoCanceler: AcousticEchoCanceler? = null

    private val _levelFlow = MutableStateFlow(0f)
    val levelFlow: StateFlow<Float> = _levelFlow.asStateFlow()

    /**
     * One take, created in [start] and captured by the read loop and by [stop], so a
     * later start()/cancel() can never make an in-flight stop() hand back the wrong
     * (or an already-deleted) file.
     */
    private class RecordingSession(val file: File)

    /**
     * Starts a recording session; returns the (still being written) PCM file it targets.
     *
     * @param echoCancel use VOICE_COMMUNICATION source + [AcousticEchoCanceler] so
     *   speaker playback (shadowing reference audio) is suppressed at the mic.
     * @param maxDurationMs hard cap; when reached the take finalizes on its own and
     *   [onAutoStop] fires once on a background thread. Null = unlimited (shadow mode).
     * @param onAutoStop notified (after release) only when [maxDurationMs] triggered the
     *   stop; at that point [stop] will still hand back the finished file.
     * @throws IllegalStateException if a recording is already active, the mic fails to
     *   initialize, or [AudioRecord.startRecording] rejects.
     * @throws SecurityException if RECORD_AUDIO permission was revoked.
     */
    suspend fun start(
        echoCancel: Boolean = false,
        maxDurationMs: Long? = null,
        onAutoStop: (() -> Unit)? = null
    ): File = withContext(Dispatchers.IO) {
        synchronized(lock) {
            check(state != State.RECORDING) { "录音已在进行中" }
            state = State.RECORDING
            sessionCancelled = false
        }
        try {
            val dir = File(context.cacheDir, "recordings")
            if (!dir.exists()) dir.mkdirs()
            val file = File(dir, "rec_${System.currentTimeMillis()}.pcm")
            val minBuf = AudioRecord.getMinBufferSize(
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT
            )
            check(minBuf > 0) { "getMinBufferSize 失败: $minBuf" }
            val bufSize = maxOf(minBuf, FRAME_BYTES * 2)
            val rec = createRecorder(bufSize, echoCancel)
            if (rec.state != AudioRecord.STATE_INITIALIZED) {
                rec.release()
                error("麦克风初始化失败 (state=${rec.state})")
            }
            rec.startRecording()
            if (echoCancel) attachEchoCanceler(rec)

            val newSession = RecordingSession(file)
            val provisioned = synchronized(lock) {
                if (sessionCancelled) {
                    // cancel() arrived while the mic was still initializing; it only
                    // holds a recorder reference after provisioning, so this start()
                    // must tear the half-built recorder down itself or the mic leaks.
                    state = State.IDLE
                    false
                } else {
                    recorder = rec
                    session = newSession
                    true
                }
            }
            if (!provisioned) {
                releaseTake(rec)
                file.delete()
                error("录音已取消")
            }
            _levelFlow.value = 0f
            scope.launch { readLoop(rec, newSession, maxDurationMs, onAutoStop) }
            file
        } catch (t: Throwable) {
            synchronized(lock) {
                if (state == State.RECORDING) {
                    state = State.IDLE
                    session = null
                }
            }
            throw t
        }
    }

    /**
     * Stops the active take, waits for the write loop to flush its last frames, and
     * returns the finished file. Suspend so coroutine callers get a fully-written file.
     *
     * Never returns a stale file from a previous take: with no live or finished session
     * (start failed, or [cancel] ran) this is null and the caller should surface
     * "录音失败，请重试" rather than upload garbage.
     */
    suspend fun stop(): File? = withContext(Dispatchers.IO) {
        val active = awaitActiveRecorder()
        if (active != null) {
            // Ask the loop to exit; it owns stop()/release() and the state flip.
            try {
                active.stop()
            } catch (e: IllegalStateException) {
                Timber.w(e, "AudioRecorder.stop: recorder already stopped")
            }
            awaitTakeFinalized()
        }
        synchronized(lock) {
            when (state) {
                State.FINISHED -> session?.file
                else -> null
            }
        }
    }

    /**
     * Returns the live recorder, waiting briefly for a [start] that is still building
     * the AudioRecord - the fast-release-after-tap window. Null means "no take to stop"
     * (IDLE/FINISHED, or start aborted).
     */
    private suspend fun awaitActiveRecorder(): AudioRecord? {
        var waited = 0L
        while (waited < AWAIT_TIMEOUT_MS) {
            val (phase, rec) = synchronized(lock) { state to recorder }
            if (phase == State.RECORDING && rec != null) return rec
            if (phase != State.RECORDING) return null
            delay(AWAIT_POLL_MS)
            waited += AWAIT_POLL_MS
        }
        Timber.e("AudioRecorder stop: take never exposed its recorder")
        return null
    }

    /** Aborts the take; safe with no active session. The file gets deleted either by the
     *  read loop's finalize or (if the take already finished) right here. */
    fun cancel() {
        val orphan: File? = synchronized(lock) {
            when (state) {
                State.RECORDING -> {
                    sessionCancelled = true
                    // Loop notices and tears down (release + delete) on its way out.
                    recorder?.let { rec ->
                        try {
                            rec.stop()
                        } catch (e: IllegalStateException) {
                            Timber.w(e, "AudioRecorder.cancel stop failed")
                        }
                    }
                    null
                }
                State.FINISHED -> {
                    state = State.IDLE
                    val f = session?.file
                    session = null
                    f
                }
                State.IDLE -> null
            }
        }
        _levelFlow.value = 0f
        releaseEchoCanceler()
        orphan?.delete()
    }

    private suspend fun readLoop(
        rec: AudioRecord,
        take: RecordingSession,
        maxDurationMs: Long?,
        onAutoStop: (() -> Unit)?
    ) {
        var stoppedByCap = false
        var consecutiveErrors = 0
        try {
            FileOutputStream(take.file).use { out ->
                val buffer = ShortArray(FRAME_SAMPLES)
                var smoothed = 0f
                val deadline = if (maxDurationMs != null) {
                    SystemClock.elapsedRealtime() + maxDurationMs
                } else {
                    Long.MAX_VALUE
                }
                while (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    if (SystemClock.elapsedRealtime() >= deadline) {
                        stoppedByCap = true
                        break
                    }
                    val read = rec.read(buffer, 0, buffer.size)
                    if (read <= 0) {
                        // Negative return = transport fault, not silence: the old bare
                        // `continue` hot-spun and starved all emissions. Pace retries and
                        // bail loudly on a sustained fault so the UI sees a final 0.
                        if (read < 0 && ++consecutiveErrors >= MAX_CONSECUTIVE_ERRORS) {
                            Timber.e(
                                "AudioRecord.read failed $consecutiveErrors times " +
                                    "(last=$read); ending take"
                            )
                            break
                        }
                        delay(READ_RETRY_DELAY_MS)
                        continue
                    }
                    consecutiveErrors = 0
                    var peak = 0
                    for (i in 0 until read) {
                        val sample = abs(buffer[i].toInt())
                        if (sample > peak) peak = sample
                    }
                    out.write(toByteArray(buffer, read))
                    smoothed = AudioLevelMapping.smooth(
                        smoothed,
                        AudioLevelMapping.peakToLevel(peak)
                    )
                    _levelFlow.value = smoothed
                }
            }
        } catch (e: Exception) {
            Timber.e(e, "AudioRecorder read loop crashed")
        } finally {
            finalizeTake(rec, take, stoppedByCap, onAutoStop)
        }
    }

    /**
     * Releases [rec] and closes the take exactly once: whoever flips RECORDING away
     * under [lock] owns the recorder, so stop(), the 30s cap, the error-abort path, and
     * [cancel] can never double-release.
     */
    private fun finalizeTake(
        rec: AudioRecord,
        take: RecordingSession,
        stoppedByCap: Boolean,
        onAutoStop: (() -> Unit)?
    ) {
        var deleteFile = false
        var notifyCapStop = false
        val ownsTeardown = synchronized(lock) {
            if (state != State.RECORDING || recorder !== rec) {
                false
            } else {
                val cancelled = sessionCancelled
                state = if (cancelled) State.IDLE else State.FINISHED
                if (cancelled) session = null
                try {
                    rec.stop()
                } catch (e: IllegalStateException) {
                    Timber.e(e, "AudioRecorder finalize stop failed")
                }
                rec.release()
                recorder = null
                deleteFile = cancelled
                notifyCapStop = stoppedByCap && !cancelled
                true
            }
        }
        // 收工: 电平归零。录音器不再持有任何历史 —— 送评这段时间屏幕上的"定格"由
        // UI 端(RecordingPulseMeter)捕获的峰值负责, 清零只影响的是下一段的起点。
        _levelFlow.value = 0f
        if (!ownsTeardown) return
        releaseEchoCanceler()
        if (deleteFile) take.file.delete()
        // Only a cap-expiry drives the submit; a plain user stop/cancel is caller-driven.
        if (notifyCapStop) onAutoStop?.invoke()
    }

    /** Waits for the read loop to leave RECORDING (it flips state on release), bounded
     *  so a wedged loop can't hang [stop] forever. */
    private suspend fun awaitTakeFinalized() {
        var waited = 0L
        while (waited < AWAIT_TIMEOUT_MS) {
            val stillActive = synchronized(lock) { state == State.RECORDING }
            if (!stillActive) return
            delay(AWAIT_POLL_MS)
            waited += AWAIT_POLL_MS
        }
        Timber.e("AudioRecorder stop timed out waiting for read loop")
    }

    private fun releaseTake(rec: AudioRecord) {
        try {
            rec.stop()
        } catch (e: IllegalStateException) {
            Timber.w(e, "AudioRecorder.releaseTake stop failed")
        }
        rec.release()
        releaseEchoCanceler()
    }

    private fun createRecorder(bufSize: Int, echoCancel: Boolean): AudioRecord {
        val source = if (echoCancel) {
            MediaRecorder.AudioSource.VOICE_COMMUNICATION
        } else {
            MediaRecorder.AudioSource.MIC
        }
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioRecord.Builder()
                .setAudioSource(source)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setSampleRate(SAMPLE_RATE)
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setChannelMask(AudioFormat.CHANNEL_IN_MONO)
                        .build()
                )
                .setBufferSizeInBytes(bufSize)
                .build()
        } else {
            @Suppress("DEPRECATION")
            AudioRecord(
                source,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize
            )
        }
    }

    private fun attachEchoCanceler(rec: AudioRecord) {
        if (!AcousticEchoCanceler.isAvailable()) return
        val canceler = AcousticEchoCanceler.create(rec.audioSessionId) ?: return
        try {
            canceler.enabled = true
            echoCanceler = canceler
        } catch (e: IllegalStateException) {
            Timber.w(e, "AcousticEchoCanceler unsupported; recording without AEC")
            canceler.release()
        }
    }

    private fun releaseEchoCanceler() {
        echoCanceler?.release()
        echoCanceler = null
    }

    private fun toByteArray(buffer: ShortArray, length: Int): ByteArray {
        val out = ByteArray(length * 2)
        for (i in 0 until length) {
            val value = buffer[i].toInt()
            out[i * 2] = (value and 0xFF).toByte()
            out[i * 2 + 1] = ((value shr 8) and 0xFF).toByte()
        }
        return out
    }

    companion object {
        const val SAMPLE_RATE = 16_000
        const val FRAME_BYTES = 1280
        const val FRAME_SAMPLES = FRAME_BYTES / 2 // 16-bit mono = 2 bytes/sample

        /** Design-doc cap for a single scored take (30s); shadow mode starts unlimited. */
        const val MAX_TAKE_MS = 30_000L

        private const val MAX_CONSECUTIVE_ERRORS = 50 // ~2s of failures at 40ms/frame
        private const val READ_RETRY_DELAY_MS = 5L
        private const val AWAIT_POLL_MS = 10L
        private const val AWAIT_TIMEOUT_MS = 2_000L
    }
}
