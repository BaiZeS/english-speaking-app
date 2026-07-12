package com.app.english.audio

import java.io.File
import java.util.Base64

/**
 * Encodes audio bytes to a base64 string for the /score JSON body.
 * Uses java.util.Base64 (available on API 26+, and pure-JVM testable).
 */
class AudioEncoder {
    fun encode(file: File): String = encode(file.readBytes())

    fun encode(bytes: ByteArray): String = Base64.getEncoder().encodeToString(bytes)
}
