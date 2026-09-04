package com.app.english.ui.components

import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.hypot
import kotlin.math.sin

/**
 * 雷达图几何(计划 §6.4「手写 Compose Canvas(RadarGeometry 纯函数 + drawPath)」)。
 *
 * 纯 Kotlin: 不 import Compose/Android, 所以普通 JVM 单测就能覆盖这套数学(见
 * `RadarGeometryTest`)。坐标系以 (0,0) 为圆心, x 向右、y 向下(与 Canvas 一致);
 * radius 只是一个标量比例 —— 传 dp 数值还是 px 数值都行, [RadarChart] 两种各算一遍。
 *
 * 角度约定: 第 0 根轴指向正上方(12 点), 其余顺时针均匀分布,
 * 即 `angle(i) = -90° + i * 360° / n`。
 */
data class RadarPoint(val x: Float, val y: Float) {
    /** 到圆心的距离, 用来断言「value=1 落在圆上」「value=0 落在圆心」。 */
    val length: Float get() = hypot(x, y)

    fun translate(dx: Float, dy: Float): RadarPoint = RadarPoint(x + dx, y + dy)
}

/** 原始 0..1 得分归一化(`null` = 该维度暂无证据, 按 0 画; NaN 同样按 0)。 */
fun Double?.toRadarValue(): Float = this?.toFloat()?.takeIf { !it.isNaN() }?.coerceIn(0f, 1f) ?: 0f

object RadarGeometry {
    /** 第一根轴朝上 => -90° = -PI/2 弧度。 */
    const val START_ANGLE_DEGREES: Float = -90f

    /** 相邻轴之间的弧度间隔; `axisCount <= 0` 时返回 0, 不给 NaN/inf。 */
    fun angleStepRadians(axisCount: Int): Float =
        if (axisCount <= 0) 0f else (2.0 * PI / axisCount).toFloat()

    /** 第 [index] 根轴的角度(弧度, 自 12 点顺时针)。 */
    fun axisAngleRadians(index: Int, axisCount: Int): Float {
        if (axisCount <= 0) return 0f
        val safeIndex = if (index >= 0) index % axisCount else (index % axisCount) + axisCount
        return (-PI / 2.0 + 2.0 * PI * safeIndex / axisCount).toFloat()
    }

    /** 长度为 1 的方向向量。 */
    fun axisUnitVector(index: Int, axisCount: Int): RadarPoint {
        val angle = axisAngleRadians(index, axisCount)
        return RadarPoint(cos(angle), sin(angle))
    }

    /** 全部轴的单位向量(画辐条与外圈网格用)。 */
    fun axisUnitVectors(axisCount: Int): List<RadarPoint> =
        (0 until axisCount).map { axisUnitVector(it, axisCount) }

    /**
     * 归一到 [0,1]: NaN -> 0, 负数(含 -inf) -> 0, 大于 1(含 +inf) -> 1。
     * (`coerceIn` 用比较运算, 无穷会被正确夹到端点, 只有 NaN 需要单独挡掉。)
     */
    fun normalizeValue(value: Float): Float = if (value.isNaN()) 0f else value.coerceIn(0f, 1f)

    /**
     * 数据多边形顶点: `values[i]` 沿第 i 根轴伸出 `values[i] * radius`。
     *
     * 顶点数 = `minOf(values.size, axes.size)`: 轴名和分数对不上时按短的来而不是
     * 抛异常(界面层数据是异步的, 允许「有轴还没分」)。
     */
    fun scaledPoints(values: List<Float>, axes: List<String>, radius: Float): List<RadarPoint> {
        val axisCount = axes.size
        if (axisCount == 0 || values.isEmpty() || radius <= 0f) return emptyList()
        return (0 until minOf(values.size, axisCount)).map { index ->
            val unit = axisUnitVector(index, axisCount)
            val reach = normalizeValue(values[index]) * radius
            RadarPoint(unit.x * reach, unit.y * reach)
        }
    }

    /** 一圈网格多边形(ring)的顶点, 满量程乘以 [fraction]。 */
    fun ringPoints(axisCount: Int, radius: Float, fraction: Float = 1f): List<RadarPoint> {
        if (axisCount <= 0 || radius <= 0f) return emptyList()
        val reach = radius * fraction.coerceIn(0f, 1f)
        return (0 until axisCount).map { index ->
            val unit = axisUnitVector(index, axisCount)
            RadarPoint(unit.x * reach, unit.y * reach)
        }
    }
}
