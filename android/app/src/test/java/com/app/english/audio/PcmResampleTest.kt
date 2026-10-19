package com.app.english.audio

import java.nio.ByteBuffer
import java.nio.ByteOrder
import org.junit.Assert.assertEquals
import org.junit.Assert.assertThrows
import org.junit.Test

/**
 * `upsamplePcm16` 只碰字节，JVM 可测（无需 Robolectric）。
 */
class PcmResampleTest {
    private fun pcm16(vararg samples: Int): ByteArray = ByteBuffer.allocate(2 * samples.size)
        .order(ByteOrder.LITTLE_ENDIAN)
        .also { buf -> samples.forEach { buf.putShort(it.toShort()) } }
        .array()

    private fun shorts(bytes: ByteArray): IntArray =
        ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().let { sb ->
            IntArray(sb.capacity()) { sb.get(it).toInt() }
        }

    @Test
    fun `16k mono becomes 48k with endpoints preserved`() {
        val out = shorts(upsamplePcm16(pcm16(0, 1000), 16_000, 48_000))
        assertEquals(6, out.size)
        assertEquals(0, out[0])
        assertEquals(1000, out[3])
        assertEquals(1000, out[5]) // 末段平推，不外推
    }

    @Test
    fun `linear interpolation between neighbours`() {
        val out = shorts(upsamplePcm16(pcm16(100, 200, 300), 24_000, 48_000))
        assertEquals(listOf(100, 150, 200, 250, 300, 300), out.toList())
    }

    @Test
    fun `same rate is a no-op`() {
        val bytes = pcm16(7, 8, 9)
        assertEquals(bytes.toList(), upsamplePcm16(bytes, 48_000, 48_000).toList())
    }

    @Test
    fun `non integer ratio is rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            upsamplePcm16(pcm16(1, 2), 22_050, 48_000)
        }
    }

    @Test
    fun `odd byte length is rejected`() {
        assertThrows(IllegalArgumentException::class.java) {
            upsamplePcm16(byteArrayOf(1), 16_000, 48_000)
        }
    }

    @Test
    fun `empty input stays empty`() {
        assertEquals(0, upsamplePcm16(byteArrayOf(), 16_000, 48_000).size)
    }
}
