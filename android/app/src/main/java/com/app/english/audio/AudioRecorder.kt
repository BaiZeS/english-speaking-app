package com.app.english.audio

import android.content.Context
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.os.Build
import java.io.File
import java.io.FileOutputStream
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.launch
import timber.log.Timber

/**
 * Records microphone audio to a raw PCM file (L16, 16kHz, mono) via [AudioRecord].
 *
 * PCM L16 16kHz mono is exactly what the Xunfei ISE speech-evaluation backend expects,
 * so the recorded bytes are uploaded as-is (no transcoding). Caller owns the lifecycle:
 * [start] then [stop] (or [cancel]).
 */
class AudioRecorder(private val context: Context) {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var recorder: AudioRecord? = null
    private var outputFile: File? = null
    private var recordJob: Job? = null

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
        // 读缓冲至少能装一个 ISE 帧 (1280B), 且不小于系统建议的最小值.
        val bufSize = maxOf(minBuf, FRAME_BYTES * 2)
        val rec = createRecorder(bufSize)
        rec.startRecording()
        recorder = rec
        outputFile = file
        recordJob = scope.launch {
            FileOutputStream(file).use { out ->
                val buffer = ByteArray(FRAME_BYTES)
                while (rec.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                    val read = rec.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        out.write(buffer, 0, read)
                    }
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

    private companion object {
        // ISE 要求 PCM L16 16kHz 单声道. 1280B = 40ms @ 16kHz/16bit/mono.
        const val SAMPLE_RATE = 16_000
        const val FRAME_BYTES = 1280
    }
}
