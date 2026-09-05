package com.app.english.ui.me

import com.app.english.domain.model.ABILITY_DIMENSIONS
import com.app.english.domain.model.AbilityTrajectoryPoint

/**
 * 画像轨迹折线的纯几何(计划 §6.4「复用 sparkline 模式手绘, 零图表依赖」)。
 *
 * 轨迹是一天一个点的序列, 该天某维没有计入证据时值为 `null` —— 折线在那里
 * **断开**(宁可断线也不把 null 当 0 分画下去, 与雷达「null 贴圆心」口径一致)。
 *
 * 输出是归一坐标(x/y 都在 0..1, y 越大分数越高), [AbilityProfileScreen] 的
 * Canvas 只负责乘上宽高再画; 数学在普通 JVM 单测([TrajectoryMathTest])锁死。
 */
object TrajectoryMath {

    /** 一个归一化坐标点(x/y 都在 0..1, y 越大分数越高)。 */
    data class Point(val x: Float, val y: Float)

    /**
     * 单个维度的折线分段: `null` 切断, 连续非空值连成一段。
     * 单点也会成段(画圆点, 不丢「只练了一天」的证据)。
     */
    fun segments(values: List<Double?>): List<List<Point>> {
        if (values.isEmpty()) return emptyList()
        val n = values.size
        val result = mutableListOf<List<Point>>()
        var current = mutableListOf<Point>()
        values.forEachIndexed { index, value ->
            if (value == null || value.isNaN()) {
                if (current.isNotEmpty()) {
                    result.add(current)
                    current = mutableListOf()
                }
                return@forEachIndexed
            }
            current.add(Point(x(index, n), y(value)))
        }
        if (current.isNotEmpty()) result.add(current)
        return result
    }

    /** 全部四维的分段(轨迹卡一次画四条线, 断线规则一致)。 */
    fun segmentsByDimension(points: List<AbilityTrajectoryPoint>): Map<String, List<List<Point>>> =
        ABILITY_DIMENSIONS.associateWith { dim ->
            segments(points.map { it.dimension(dim) })
        }

    private fun x(index: Int, count: Int): Float =
        if (count <= 1) 0.5f else index.toFloat() / (count - 1).toFloat()

    private fun y(score: Double): Float = (score / 100.0).toFloat().coerceIn(0f, 1f)
}
