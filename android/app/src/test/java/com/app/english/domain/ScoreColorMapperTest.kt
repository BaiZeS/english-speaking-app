package com.app.english.domain

import org.junit.Assert.assertEquals
import org.junit.Test

class ScoreColorMapperTest {
    @Test
    fun scoreAtOrAboveGreenThreshold_isGreen() {
        assertEquals(ScoreLevel.GREEN, ScoreColorMapper.level(100.0))
        assertEquals(ScoreLevel.GREEN, ScoreColorMapper.level(90.0))
        assertEquals(ScoreLevel.GREEN, ScoreColorMapper.level(ScoreColorMapper.GREEN_THRESHOLD))
    }

    @Test
    fun scoreJustBelowGreen_isYellow() {
        assertEquals(ScoreLevel.YELLOW, ScoreColorMapper.level(84.9))
        assertEquals(ScoreLevel.YELLOW, ScoreColorMapper.level(70.0))
    }

    @Test
    fun scoreAtYellowThreshold_isYellow() {
        assertEquals(ScoreLevel.YELLOW, ScoreColorMapper.level(ScoreColorMapper.YELLOW_THRESHOLD))
    }

    @Test
    fun scoreJustBelowYellow_isRed() {
        assertEquals(ScoreLevel.RED, ScoreColorMapper.level(59.9))
        assertEquals(ScoreLevel.RED, ScoreColorMapper.level(1.0))
    }

    @Test
    fun scoreZero_isRed() {
        assertEquals(ScoreLevel.RED, ScoreColorMapper.level(0.0))
    }
}
