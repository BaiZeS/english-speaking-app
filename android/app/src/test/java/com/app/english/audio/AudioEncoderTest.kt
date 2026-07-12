package com.app.english.audio

import java.util.Base64
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Test

class AudioEncoderTest {
    private val encoder = AudioEncoder()

    @Test
    fun encodeBytes_roundTripsThroughBase64() {
        val original = byteArrayOf(0, 1, 2, 3, 127, -128, 10, 20, 30, -1)
        val encoded = encoder.encode(original)
        val decoded = Base64.getDecoder().decode(encoded)
        assertArrayEquals(original, decoded)
    }

    @Test
    fun encodeBytes_matchesStandardBase64NoWrap() {
        val original = "hello audio world".toByteArray()
        val encoded = encoder.encode(original)
        assertEquals(Base64.getEncoder().encodeToString(original), encoded)
    }

    @Test
    fun encodeEmptyBytes_returnsEmptyString() {
        assertEquals("", encoder.encode(ByteArray(0)))
    }

    @Test
    fun encodeBytes_doesNotContainNewlines() {
        val original = ByteArray(1000) { it.toByte() }
        val encoded = encoder.encode(original)
        assertEquals(false, encoded.contains("\n"))
    }
}
