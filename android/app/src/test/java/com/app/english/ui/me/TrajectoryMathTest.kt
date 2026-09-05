package com.app.english.ui.me

import com.app.english.domain.model.AbilityTrajectoryPoint
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 画像轨迹折线的纯几何锁: null 断线、单点保留、坐标归一 —— 画出来的线必须和
 * 数据诚实对齐(TrajectoryMath 不 import 任何 Android 类)。
 */
class TrajectoryMathTest {

    @Test
    fun emptyValuesYieldNoSegments() {
        assertTrue(TrajectoryMath.segments(emptyList()).isEmpty())
    }

    @Test
    fun contiguousValuesFormOneSegment() {
        val segments = TrajectoryMath.segments(listOf(80.0, 90.0, 70.0))
        assertEquals(1, segments.size)
        assertEquals(3, segments.single().size)
    }

    @Test
    fun nullBreaksTheLineIntoSegments() {
        val segments = TrajectoryMath.segments(listOf(80.0, null, 70.0, 90.0, null, 60.0))
        assertEquals(3, segments.size)
        assertEquals(1, segments[0].size)
        assertEquals(2, segments[1].size)
        assertEquals(1, segments[2].size)
    }

    @Test
    fun singleDayStillProducesAPoint() {
        val segments = TrajectoryMath.segments(listOf(55.0))
        val point = segments.single().single()
        assertEquals("只有一天时点画在横轴正中", 0.5f, point.x)
        assertEquals(0.55f, point.y)
    }

    @Test
    fun pointsSpreadEvenlyAndYScalesWithScore() {
        val segments = TrajectoryMath.segments(listOf(0.0, 50.0, 100.0))
        val line = segments.single()
        assertEquals(0.0f, line[0].x)
        assertEquals(0.5f, line[1].x)
        assertEquals(1.0f, line[2].x)
        assertEquals(0.0f, line[0].y)
        assertEquals(0.5f, line[1].y)
        assertEquals(1.0f, line[2].y)
    }

    @Test
    fun scoresClampIntoTheUnitSquare() {
        val segments = TrajectoryMath.segments(listOf(120.0, -5.0))
        val line = segments.single()
        assertEquals(1.0f, line[0].y)
        assertEquals(0.0f, line[1].y)
    }

    @Test
    fun segmentsByDimensionCoversAllFourAxes() {
        val map = TrajectoryMath.segmentsByDimension(
            listOf(
                AbilityTrajectoryPoint(date = "2026-09-04", pronunciation = 80.0, events = 1)
            )
        )
        assertEquals(
            setOf("pronunciation", "grammar", "vocabulary", "fluency"),
            map.keys
        )
        assertEquals(1, map["pronunciation"]!!.size)
        assertTrue("没证据的维不该有线", map.getValue("grammar").isEmpty())
    }
}
