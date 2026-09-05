package com.app.english.ui.me

import com.app.english.data.remote.AbilityResponseDto
import com.app.english.data.remote.AbilityTrajectoryPointDto
import com.app.english.data.remote.toDomain
import com.app.english.data.repository.sanitizeAbilityDays
import com.app.english.domain.model.AbilityProfile
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P7 画像数据链的纯映射锁: `GET /ability` DTO -> 领域 -> 雷达/轨迹/今日推荐输入。
 * 全部普通 JVM 断言, 不碰 Android 类。
 */
class AbilityProfileMappingTest {

    @Test
    fun abilityDtoMapsProfileCountsAndTrajectory() {
        val dto = AbilityResponseDto(
            deviceId = "dev-1",
            userFound = true,
            profile = mapOf(
                "pronunciation" to 82.0,
                "grammar" to null,
                "vocabulary" to 71.5,
                "fluency" to null
            ),
            n = mapOf("pronunciation" to 3, "grammar" to 0),
            cefrLevel = "B1",
            assessmentCefr = "A2",
            bandLocked = true,
            derivedLevel = "B1",
            days = 30,
            trajectory = listOf(
                AbilityTrajectoryPointDto(
                    date = "2026-09-04",
                    pronunciation = 80.0,
                    grammar = null,
                    vocabulary = 70.0,
                    fluency = null,
                    events = 2
                )
            ),
            realEvents = 5
        )
        val profile = dto.toDomain()
        assertEquals(82.0, profile.pronunciation!!, 0.0)
        assertNull(profile.grammar)
        assertEquals(71.5, profile.vocabulary!!, 0.0)
        assertNull(profile.fluency)
        assertEquals(3, profile.sampleCount("pronunciation"))
        assertEquals(0, profile.sampleCount("grammar"))
        assertEquals("缺样本的维默认 0 而不是抛", 0, profile.sampleCount("fluency"))
        assertEquals("B1", profile.cefrLevel)
        assertEquals("A2", profile.assessmentCefr)
        assertTrue(profile.bandLocked)
        assertEquals("2026-09-04", profile.trajectory.single().date)
        assertTrue(profile.isAssessed)
    }

    @Test
    fun emptyProfileIsHonestAllNull() {
        val profile = AbilityResponseDto(deviceId = "dev-1", days = 30).toDomain()
        assertNull(profile.pronunciation)
        assertNull(profile.cefrLevel)
        assertFalse(profile.isAssessed)
        assertNull("空画像不推荐(走 curated 兜底)", profile.weakestDimension())
    }

    @Test
    fun weakestDimensionIsTheLowestScoredDimension() {
        val profile = AbilityProfile(pronunciation = 90.0, grammar = 55.0, fluency = 61.0)
        assertEquals("grammar", profile.weakestDimension())
    }

    @Test
    fun weakestDimensionTieBreaksInFixedOrder() {
        val profile = AbilityProfile(pronunciation = 60.0, grammar = 60.0, vocabulary = 60.0)
        assertEquals("发音/语法/词汇同分时取固定顺序的第一维", "pronunciation", profile.weakestDimension())
    }

    @Test
    fun assessedIsTrueWhenEitherCefrFieldIsPresent() {
        assertTrue(AbilityProfile(assessmentCefr = "B1").isAssessed)
        assertTrue(AbilityProfile(cefrLevel = "A2").isAssessed)
        assertFalse(AbilityProfile(pronunciation = 90.0).isAssessed)
    }

    @Test
    fun daysSanitizeKeepsWhitelistAndDefaultsTheRest() {
        assertEquals(7, sanitizeAbilityDays(7))
        assertEquals(30, sanitizeAbilityDays(30))
        assertEquals(90, sanitizeAbilityDays(90))
        assertEquals(30, sanitizeAbilityDays(0))
        assertEquals(30, sanitizeAbilityDays(14))
        assertEquals(30, sanitizeAbilityDays(45))
    }

    @Test
    fun fromProfileFeedsTheRadarWithRealValues() {
        val profile = AbilityProfile(pronunciation = 80.0, vocabulary = 40.0)
        val axes = AbilityAxes.fromProfile(profile)
        assertEquals(0.80f, axes.radarValues()[0])
        assertEquals(0.40f, axes.radarValues()[2])
        assertEquals(listOf("语法", "流利度"), axes.missingLabels())
    }

    @Test
    fun fromNullProfileFallsBackToEmpty() {
        assertTrue(AbilityAxes.fromProfile(null).isEmpty)
    }

    @Test
    fun lacksEvidenceFlagsZeroSampleDimensions() {
        val profile = AbilityProfile(
            pronunciation = 80.0,
            sampleCounts = mapOf("pronunciation" to 2)
        )
        assertFalse(profile.lacksEvidence("pronunciation"))
        assertTrue(profile.lacksEvidence("grammar"))
        assertTrue("样本表缺键也按 n=0 处理", profile.lacksEvidence("fluency"))
    }
}
