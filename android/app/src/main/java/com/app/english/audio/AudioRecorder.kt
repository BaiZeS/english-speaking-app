package com.app.english.audio

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import java.io.File
import java.io.FileOutputStream
import kotlin.math.abs
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.flow.asSharedFlow
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Records microphone audio to a raw PCM file (L16, 16kHz, mono) via [AudioRecord].
 *
 * PCM L16 16kHz mono is exactly what the Xunfei ISE speech-evaluation backend expects,
 * so the recorded bytes are uploaded as-is (no transcoding). Caller owns the lifecycle:
 * [start] then [stop] (or [cancel]).
 *
 * While recording, [levelFlow] emits normalized amplitude values (0..1) at roughly
 * 30Hz so the UI can render a live VU meter. Values are derived from the peak
 * absolute PCM sample in each frame; we never persist the level samples.
 */
class AudioRecorder(private val context: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var recorder: AudioRecord? = null
    private var outputFile: File? = null
    private var recordJob: Job? = null

    private val _levelFlow = MutableSharedFlow<Float>(
        replay = 0,
        extraBufferCapacity = 8
    )
    val levelFlow: SharedFlow<Float> = _levelFlow.asSharedFlow()

    fun start(): File {
        val dir = File(context.cacheDir, "recordings")
        if (!dir.exists()) dir.mkdirs()
        val file = File(dir, "rec_${System.currentTimeMillis()}.pcm")
        val minBuf = AudioRecord.getMinBufferSize(
            SAMPLE_RATE,
            AudioFormat.CHANNEL_IN_MONO,
            AudioFormat.ENCODING_PCM_16BIT
        )
        require(minBuf > 0) { "getMinBufferSize failed: $minBuf" }
        val bufSize = maxOf(minBuf, FRAME_BYTES * 2)
        val rec = createRecorder(bufSize)
        rec.startRecording()
        recorder = rec
        outputFile = file
        recordJob = scope.launch {
            FileOutputStream(file).use { out ->
                val buffer = ShortArray(FRAME_SAMPLES)
                while (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    val read = rec.read(buffer, 0, buffer.size)
                    if (read <= 0) continue
                    var peak = 0
                    for (i in 0 until read) {
                        val sample = abs(buffer[i].toInt())
                        if (sample > peak) peak = sample
                    }
                    out.write(toByteArray(buffer, read))
                    val normalized = (peak.toFloat() / Short.MAX_VALUE.toFloat()).coerceIn(0f, 1f)
                    _levelFlow.tryEmit(normalized)
                }
            }
        }
        return file
    }

    /**
     * Stop recording and wait for the write loop to flush remaining audio to disk.
     * Suspend so callers in a coroutine get a fully-written [File] back.
     */
    suspend fun stop(): File? {
        val rec = recorder ?: return outputFile
        rec.stop()
        rec.release()
        recorder = null
        val job = recordJob
        recordJob = null
        job?.join()
        return outputFile
    }

    fun cancel() {
        recorder?.run {
            try {
                stop()
            } catch (e: IllegalStateException) {
                Timber.e(e, "AudioRecorder.cancel stop failed")
            }
            release()
        }
        recorder = null
        recordJob?.cancel()
        recordJob = null
        outputFile?.delete()
        outputFile = null
    }

    private fun createRecorder(bufSize: Int): AudioRecord =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            AudioRecord.Builder()
                .setAudioSource(MediaRecorder.AudioSource.MIC)
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
                MediaRecorder.AudioSource.MIC,
                SAMPLE_RATE,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                bufSize
            )
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

    private companion object {
        const val SAMPLE_RATE = 16_000
        const val FRAME_BYTES = 1280
        const val FRAME_SAMPLES = FRAME_BYTES / 2 // 16-bit mono = 2 bytes/sample
    }
}
