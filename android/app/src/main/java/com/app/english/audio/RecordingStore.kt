package com.app.english.audio

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.FileOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder
import javax.inject.Inject
import javax.inject.Singleton
import timber.log.Timber

/**
 * Retains user recordings on disk so they can be replayed and compared with
 * the reference TTS after scoring.
 *
 * [AudioRecorder] writes raw headerless PCM (L16, 16kHz, mono); this store
 * wraps those bytes in a standard 44-byte WAV header (same layout as the
 * backend's `_pcm16_to_wav`) and files them under
 * `filesDir/recordings/{book}/{lessonId}/{lineId}-{timestamp}.wav`. Only the
 * newest [MAX_PER_LINE] recordings per line are kept. Methods perform disk IO
 * and must be called on a background dispatcher.
 */
@Singleton
class RecordingStore @Inject constructor(@ApplicationContext private val context: Context) {
    /**
     * Copies [pcmFile] into the store as a WAV file and prunes older takes of
     * the same line. Returns the written file.
     */
    fun saveRecording(book: String, lessonId: Int, lineId: String, pcmFile: File): File {
        val dir = lineDir(book, lessonId)
        if (!dir.exists()) dir.mkdirs()
        val target = File(dir, "${sanitize(lineId)}-${System.currentTimeMillis()}.wav")
        val pcm = pcmFile.readBytes()
        FileOutputStream(target).use { out ->
            out.write(wavHeader(pcm.size))
            out.write(pcm)
        }
        prune(dir, lineId)
        return target
    }

    private fun lineDir(book: String, lessonId: Int): File =
        File(File(File(context.filesDir, "recordings"), sanitize(book)), lessonId.toString())

    private fun isRecordingOf(file: File, lineId: String): Boolean {
        // 精确匹配 "{lineId}-{毫秒时间戳}.wav": startsWith 会让 "biz-L1-A1" 误匹配
        // "biz-L1-A1-s1-*.wav" (跟读拆句 id 与整句 id 同目录共存).
        val pattern = Regex("^${Regex.escape(sanitize(lineId))}-\\d+\\.wav$")
        return file.isFile && pattern.matches(file.name)
    }

    private fun prune(dir: File, lineId: String) {
        val saved = dir.listFiles { file -> isRecordingOf(file, lineId) } ?: return
        if (saved.size <= MAX_PER_LINE) return
        saved.sortedByDescending { it.lastModified() }
            .drop(MAX_PER_LINE)
            .forEach { file ->
                if (!file.delete()) Timber.w("Failed to prune old recording ${file.name}")
            }
    }

    private fun sanitize(value: String): String = value.replace(SANITIZE, "_")

    /** Canonical 44-byte RIFF/WAVE header for PCM L16 mono at [SAMPLE_RATE]. */
    private fun wavHeader(dataSize: Int): ByteArray = ByteBuffer.allocate(HEADER_BYTES)
        .order(ByteOrder.LITTLE_ENDIAN)
        .put(RIFF)
        .putInt(dataSize + CHUNK_SIZE_OFFSET)
        .put(WAVE)
        .put(FMT)
        .putInt(FMT_CHUNK_SIZE)
        .putShort(AUDIO_FORMAT_PCM)
        .putShort(CHANNELS_MONO)
        .putInt(SAMPLE_RATE)
        .putInt(SAMPLE_RATE * BLOCK_ALIGN)
        .putShort(BLOCK_ALIGN)
        .putShort(BITS_PER_SAMPLE)
        .put(DATA)
        .putInt(dataSize)
        .array()

    private companion object {
        const val MAX_PER_LINE = 3
        const val SAMPLE_RATE = 16_000
        const val HEADER_BYTES = 44
        const val CHUNK_SIZE_OFFSET = 36
        const val FMT_CHUNK_SIZE = 16
        const val AUDIO_FORMAT_PCM: Short = 1
        const val CHANNELS_MONO: Short = 1
        const val BLOCK_ALIGN: Short = 2
        const val BITS_PER_SAMPLE: Short = 16
        val RIFF = "RIFF".toByteArray(Charsets.US_ASCII)
        val WAVE = "WAVE".toByteArray(Charsets.US_ASCII)
        val FMT = "fmt ".toByteArray(Charsets.US_ASCII)
        val DATA = "data".toByteArray(Charsets.US_ASCII)
        val SANITIZE = Regex("[^A-Za-z0-9_-]")
    }
}
