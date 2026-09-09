package com.app.english.audio

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class AudioLevelMappingTest {

    @Test
    fun silence_mapsToZero() {
        assertEquals(0f, AudioLevelMapping.peakToLevel(0), 0f)
        assertEquals(0f, AudioLevelMapping.peakToLevel(-5), 0f)
    }

    @Test
    fun quietRoomNoise_staysNearBottom() {
        // peak 150 ~= -46.8 dBFS -> (50-46.8)/44 ~= 0.07
        assertTrue(AudioLevelMapping.peakToLevel(150) < 0.15f)
    }

    @Test
    fun normalSpeechPeak_lightsPastHalf() {
        // peak 3000 -> -20.8 dBFS -> (50-20.8)/44 ~= 0.66
        assertEquals(0.66f, AudioLevelMapping.peakToLevel(3000), 0.05f)
    }

    @Test
    fun loudPeak_reachesRedBand() {
        // peak 12000 -> -8.7 dBFS -> (50-8.7)/44 ~= 0.94 (> 0.85 red band)
        assertTrue(AudioLevelMapping.peakToLevel(12000) > 0.85f)
    }

    @Test
    fun fullScale_clampsToOne() {
        assertEquals(1f, AudioLevelMapping.peakToLevel(32767), 0f)
        assertEquals(1f, AudioLevelMapping.peakToLevel(Short.MAX_VALUE.toInt() + 1), 0f)
    }

    @Test
    fun mapping_isMonotonic() {
        val peaks = intArrayOf(1, 150, 800, 3000, 12000, 32767)
        val levels = peaks.map(AudioLevelMapping::peakToLevel)
        for (i in 1 until levels.size) {
            assertTrue("level must not decrease as peak grows ($peaks)", levels[i] >= levels[i - 1])
        }
    }

    @Test
    fun smooth_risesFasterThanItFalls() {
        val rise = AudioLevelMapping.smooth(0f, 1f)
        val fall = AudioLevelMapping.smooth(1f, 0f)
        assertTrue(rise > 0.5f)
        assertTrue(fall < 0.9f)
        assertEquals(0.7f, rise, 1e-5f)
        assertEquals(0.75f, fall, 1e-5f)
    }

    @Test
    fun smooth_neverOvershootsTargetRange() {
        assertEquals(0.38f, AudioLevelMapping.smooth(0.1f, 0.5f), 1e-5f)
        assertEquals(0.4f, AudioLevelMapping.smooth(0.5f, 0.1f), 1e-5f)
        assertEquals(0.3f, AudioLevelMapping.smooth(0.3f, 0.3f), 1e-5f)
    }
}
