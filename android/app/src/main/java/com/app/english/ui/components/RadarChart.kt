package com.app.english.ui.components

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.DrawScope
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * 能力画像雷达图(计划 §6.4: 手写 Canvas, 零新依赖 —— 与 Dashboard 的 sparkline
 * 同一套做法)。数学全部走 [RadarGeometry] 纯函数, 这里只负责画。
 *
 * @param values 每根轴的取值, 已归一到 0..1(分数请传 `score / 100f`)。
 * @param axes 轴名, 4 维画像传 [com.app.english.ui.me.AbilityAxes.LABELS]。
 */
@Composable
fun RadarChart(
    values: List<Float>,
    axes: List<String>,
    modifier: Modifier = Modifier,
    rings: Int = 4,
    labelSpace: Dp = 30.dp,
    valueColor: Color = MaterialTheme.colorScheme.primary
) {
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    val labelColor = MaterialTheme.colorScheme.onSurfaceVariant
    val fillColor = valueColor.copy(alpha = 0.18f)

    BoxWithConstraints(
        modifier = modifier.aspectRatio(1f),
        contentAlignment = Alignment.Center
    ) {
        val axisCount = axes.size
        // 画布留出一圈 labelSpace 给轴名, 半径口径与下面的标签定位共用同一个值。
        val radius = minOf(maxWidth, maxHeight) / 2f - labelSpace
        val labelRadius = radius + labelSpace * 0.6f

        Box(modifier = Modifier.fillMaxSize().padding(labelSpace)) {
            Canvas(modifier = Modifier.fillMaxSize()) {
                val reach = radius.coerceAtLeast(0.dp).toPx()
                if (axisCount < 3 || reach <= 0f) return@Canvas
                drawRadarGrid(
                    axisCount = axisCount,
                    radius = reach,
                    rings = rings,
                    color = gridColor
                )
                drawRadarSeries(
                    values = values,
                    axisCount = axisCount,
                    radius = reach,
                    fillColor = fillColor,
                    lineColor = valueColor
                )
            }
        }

        if (axisCount >= 3) {
            axes.forEachIndexed { index, label ->
                val unit = RadarGeometry.axisUnitVector(index, axisCount)
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelMedium,
                    color = labelColor,
                    textAlign = TextAlign.Center,
                    maxLines = 1,
                    modifier = Modifier
                        .align(Alignment.Center)
                        .offset(
                            x = (unit.x * labelRadius.value).dp,
                            y = (unit.y * labelRadius.value).dp
                        )
                )
            }
        }
    }
}

/** 同心多边形网格 + 辐条。 */
private fun DrawScope.drawRadarGrid(axisCount: Int, radius: Float, rings: Int, color: Color) {
    val center = Offset(size.width / 2f, size.height / 2f)
    val levels = rings.coerceIn(1, 8)
    for (level in 1..levels) {
        val fraction = level.toFloat() / levels.toFloat()
        val ring = RadarGeometry.ringPoints(axisCount, radius, fraction)
        drawPath(closedPath(ring, center), color = color, style = Stroke(width = 1f))
    }
    RadarGeometry.axisUnitVectors(axisCount).forEach { unit ->
        drawLine(
            color = color,
            start = center,
            end = Offset(center.x + unit.x * radius, center.y + unit.y * radius),
            strokeWidth = 1f
        )
    }
}

/** 数据多边形: 半透明填充 + 描边 + 顶点圆点。 */
private fun DrawScope.drawRadarSeries(
    values: List<Float>,
    axisCount: Int,
    radius: Float,
    fillColor: Color,
    lineColor: Color
) {
    val center = Offset(size.width / 2f, size.height / 2f)
    val axes = List(axisCount) { index -> index.toString() }
    val shaped = RadarGeometry.scaledPoints(values, axes, radius)
    val points = shaped.map { it.translate(center.x, center.y) }
    if (points.size < 2) return
    val path = closedPath(points, Offset.Zero)
    drawPath(path = path, color = fillColor)
    drawPath(path = path, color = lineColor, style = Stroke(width = 3f))
    points.forEach { point ->
        drawCircle(color = lineColor, radius = 5f, center = Offset(point.x, point.y))
    }
}

private fun closedPath(points: List<RadarPoint>, origin: Offset): Path {
    val path = Path()
    if (points.isEmpty()) return path
    points.forEachIndexed { index, point ->
        val x = origin.x + point.x
        val y = origin.y + point.y
        if (index == 0) path.moveTo(x, y) else path.lineTo(x, y)
    }
    path.close()
    return path
}
