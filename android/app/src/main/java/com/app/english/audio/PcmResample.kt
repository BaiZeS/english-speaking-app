package com.app.english.audio

import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * 整数比线性插值上采样 mono PCM16（Little-Endian）。
 *
 * 存在理由：Android 只强制设备支持 44.1k/48k 播放采样率，实测华为/鸿蒙折叠屏
 * 在 16k（录音回放）与 24k（TTS）上起不了 AudioTrack，表现是「所有声音都不出声」。
 * 16k→48k、24k→48k 都是整数倍，插值即可，不必为重采样引第三方库。
 * 末段平推最后一个采样值：外推会凭空造出信号。
 */
internal fun upsamplePcm16(pcm: ByteArray, srcRateHz: Int, dstRateHz: Int): ByteArray {
    require(srcRateHz > 0) { "srcRateHz 必须为正: $srcRateHz" }
    require(dstRateHz % srcRateHz == 0) { "只支持整数倍上采样: $srcRateHz -> $dstRateHz" }
    require(pcm.size % 2 == 0) { "PCM16 长度必须为偶数字节，实得 ${pcm.size}" }
    val factor = dstRateHz / srcRateHz
    if (factor == 1 || pcm.isEmpty()) return pcm

    val src = ShortArray(pcm.size / 2)
    ByteBuffer.wrap(pcm).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().get(src)

    val last = src.size - 1
    val dst = ShortArray(src.size * factor)
    for (i in dst.indices) {
        val base = i / factor
        val frac = i % factor
        val a = src[base]
        val b = src[(base + 1).coerceAtMost(last)]
        dst[i] = if (frac == 0) a else (a + (b - a) * frac / factor).toShort()
    }

    val out = ByteArray(dst.size * 2)
    ByteBuffer.wrap(out).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer().put(dst)
    return out
}
