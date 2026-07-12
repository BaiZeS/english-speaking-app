package com.app.english.audio

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import java.io.File
import timber.log.Timber

/**
 * Records microphone audio to a .m4a (AAC in MPEG-4) file via MediaRecorder.
 * Caller owns the lifecycle: [start] then [stop] (or [cancel]).
 */
class AudioRecorder(private val context: Context) {
    private val cacheDir = context.cacheDir
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null

    fun start(): File {
        val dir = File(cacheDir, "recordings")
        if (!dir.exists()) dir.mkdirs()
        val file = File(dir, "rec_${System.currentTimeMillis()}.m4a")
        val rec = createRecorder()
        rec.setAudioSource(MediaRecorder.AudioSource.MIC)
        rec.setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
        rec.setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
        rec.setAudioEncodingBitRate(BIT_RATE)
        rec.setAudioSamplingRate(SAMPLE_RATE)
        rec.setOutputFile(file.absolutePath)
        rec.prepare()
        rec.start()
        recorder = rec
        outputFile = file
        return file
    }

    fun stop(): File? {
        val rec = recorder ?: return outputFile
        return try {
            rec.stop()
            rec.release()
            recorder = null
            outputFile
        } catch (e: RuntimeException) {
            // stop() throws if no valid audio was captured; clean up.
            Timber.e(e, "MediaRecorder.stop failed")
            rec.release()
            recorder = null
            outputFile?.delete()
            outputFile = null
            null
        }
    }

    fun cancel() {
        recorder?.run {
            try {
                stop()
            } catch (e: RuntimeException) {
                Timber.e(e, "MediaRecorder.cancel stop failed")
            }
            release()
        }
        recorder = null
        outputFile?.delete()
        outputFile = null
    }

    private fun createRecorder(): MediaRecorder =
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
            MediaRecorder(context)
        } else {
            @Suppress("DEPRECATION")
            MediaRecorder()
        }

    companion object {
        private const val BIT_RATE = 64_000
        private const val SAMPLE_RATE = 44_100
    }
}
