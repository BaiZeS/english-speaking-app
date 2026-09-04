package com.app.english.ui.components

import kotlin.math.PI
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `RadarGeometry` 的纯数学契约(计划 §七 P7 验收门同款, 提前在 P5 落地)。
 * 没有 Compose runtime: 这些断言跑普通 JVM, 不需要 Robolectric。
 */
class RadarGeometryTest {
    private val axes = listOf("发音", "语法", "词汇", "流利度")

    private fun Float.d(): Double = toDouble()

    @Test
    fun anglesAreEvenlySpaced() {
        val step = RadarGeometry.angleStepRadians(4).d()
        assertEquals(PI / 2.0, step, EPS)
        assertEquals(PI / 3.0, RadarGeometry.angleStepRadians(6).d(), EPS)
        for (index in 1 until 4) {
            val gap = RadarGeometry.axisAngleRadians(index, 4).d() -
                RadarGeometry.axisAngleRadians(index - 1, 4).d()
            assertEquals(PI / 2.0, gap, EPS)
        }
    }

    @Test
    fun firstAxisPointsStraightUp() {
        assertEquals(-PI / 2.0, RadarGeometry.axisAngleRadians(0, 4).d(), EPS)
        val up = RadarGeometry.axisUnitVector(0, 4)
        assertEquals(0.0, up.x.d(), EPS)
        assertEquals(-1.0, up.y.d(), EPS)
    }

    @Test
    fun axesGoClockwiseForFourDimensions() {
        val vectors = RadarGeometry.axisUnitVectors(4)
        // 顺时针: 上(0,-1) -> 右(1,0) -> 下(0,1) -> 左(-1,0), 与
        // `fullValuesLandOnCircle` 对 points[1].x == +radius 的口径一致。
        assertEquals(1.0, vectors[1].x.d(), EPS)
        assertEquals(0.0, vectors[1].y.d(), EPS)
        assertEquals(0.0, vectors[2].x.d(), EPS)
        assertEquals(1.0, vectors[2].y.d(), EPS)
        assertEquals(-1.0, vectors[3].x.d(), EPS)
        vectors.forEach { unit ->
            assertEquals("每根轴都是单位向量", 1.0, unit.length.d(), EPS)
        }
    }

    @Test
    fun zeroValuesCollapseToCentre() {
        val points = RadarGeometry.scaledPoints(List(4) { 0f }, axes, radius = 40f)
        assertEquals(4, points.size)
        points.forEach { point ->
            assertEquals(0.0, point.length.d(), EPS)
        }
    }

    @Test
    fun fullValuesLandOnCircle() {
        val radius = 40f
        val points = RadarGeometry.scaledPoints(List(4) { 1f }, axes, radius)
        points.forEach { point -> assertEquals(radius.d(), point.length.d(), EPS) }
        // 顶点顺序: 上、右、下、左
        assertEquals(-(radius.d()), points[0].y.d(), EPS)
        assertEquals(radius.d(), points[1].x.d(), EPS)
    }

    @Test
    fun midValueLandsHalfwayOut() {
        val only = RadarGeometry.scaledPoints(listOf(0.5f), axes, radius = 40f)
        assertEquals(1, only.size)
        assertEquals(20.0, only[0].length.d(), EPS)
    }

    @Test
    fun negativeAndNaNAndOvershootClamp() {
        val points = RadarGeometry.scaledPoints(
            values = listOf(-0.5f, Float.NaN, 2f, 0.25f),
            axes = axes,
            radius = 10f
        )
        assertEquals(0.0, points[0].length.d(), EPS)
        assertEquals(0.0, points[1].length.d(), EPS)
        assertEquals(10.0, points[2].length.d(), EPS)
        assertEquals(2.5, points[3].length.d(), EPS)
    }

    @Test
    fun pointCountFollowsTheShorterSide() {
        assertEquals(2, RadarGeometry.scaledPoints(List(2) { 1f }, axes, 10f).size)
        assertEquals(4, RadarGeometry.scaledPoints(List(9) { 1f }, axes, 10f).size)
    }

    @Test
    fun degenerateInputsReturnEmptyInsteadOfThrowing() {
        assertTrue(RadarGeometry.scaledPoints(emptyList(), axes, 10f).isEmpty())
        assertTrue(RadarGeometry.scaledPoints(listOf(1f), emptyList(), 10f).isEmpty())
        assertTrue(RadarGeometry.scaledPoints(listOf(1f), axes, 0f).isEmpty())
        assertTrue(RadarGeometry.scaledPoints(listOf(1f), axes, -5f).isEmpty())
        assertTrue(RadarGeometry.ringPoints(0, 10f).isEmpty())
        assertTrue(RadarGeometry.ringPoints(4, 0f).isEmpty())
        assertEquals(0.0, RadarGeometry.angleStepRadians(0).d(), 0.0)
        assertEquals(0.0, RadarGeometry.axisAngleRadians(3, 0).d(), 0.0)
    }

    @Test
    fun ringFractionShrinksTheOutline() {
        val inner = RadarGeometry.ringPoints(4, radius = 20f, fraction = 0.5f)
        assertEquals(4, inner.size)
        inner.forEach { point -> assertEquals(10.0, point.length.d(), EPS) }
        // 越界的 fraction 夹在 0..1
        RadarGeometry.ringPoints(4, 20f, 3f).forEach {
            assertEquals(20.0, it.length.d(), EPS)
        }
    }

    @Test
    fun translateMovesPointsByTheCentre() {
        val moved = RadarGeometry.axisUnitVector(0, 4).translate(100f, 50f)
        assertEquals(100.0, moved.x.d(), EPS)
        assertEquals(49.0, moved.y.d(), EPS)
    }

    @Test
    fun normalizeValueAndRadarValueHelpers() {
        assertEquals(0.0, RadarGeometry.normalizeValue(Float.NaN).d(), 0.0)
        assertEquals(0.0, RadarGeometry.normalizeValue(-3f).d(), 0.0)
        assertEquals(0.7, RadarGeometry.normalizeValue(0.7f).d(), 1e-5)
        assertEquals(1.0, RadarGeometry.normalizeValue(11f).d(), 0.0)
        assertEquals(0.0, null.toRadarValue().d(), 0.0)
        assertEquals(0.42, 0.42.toRadarValue().d(), 1e-5)
        assertEquals(1.0, 1.9.toRadarValue().d(), 0.0)
        assertEquals(0.0, Double.NaN.toRadarValue().d(), 0.0)
    }

    private companion object {
        const val EPS = 1e-3
    }
}
