package com.app.english.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.app.english.domain.ScoreColorMapper
import com.app.english.ui.theme.color

/**
 * 环形分数 —— 反馈卡头的**共用原子件**(打基础 [com.app.english.ui.scenes.DrillFeedbackCard]
 * / 播读 [com.app.english.ui.player.ScorePanel] / 自由对话 FreeScoreCard 三处同源)。
 *
 * 配色不凭审美: 底环用 `surfaceVariant`, 进度环与中心数字一律取
 * `ScoreColorMapper.level(score).color()`(绿 ≥85 / 黄 ≥60 / 红)。这条色带是**冻结规格**,
 * 全 App 只有这一个来源, 这里只消费、不重新定义。
 *
 * 形状是 `ReviewScreen.OverallRing` 的同源套路, 但那只环属于复盘页的 140dp 大卡、语义是
 * "整场总评", 没有被抽成公共件 —— 本文件承担的是"卡片头部小环"这个重复出现的形态。
 *
 * 入场动画刻意用 `Animatable` 而不是 `animateFloatAsState`: 后者在**首次组成**时把目标值
 * 当初始值, 而反馈卡恰恰是在评分到手那一刻才插入组合树的, 于是"从 0 长到这次分数"一次也
 * 看不到。`Animatable(0f)` + `LaunchedEffect(score)` 才有第一次的清扫。
 */
@Composable
fun ScoreRing(
    score: Double,
    modifier: Modifier = Modifier,
    diameter: Dp = RING_DIAMETER,
    strokeWidth: Dp = RING_STROKE_WIDTH
) {
    val bandColor = ScoreColorMapper.level(score).color()
    val trackColor = MaterialTheme.colorScheme.surfaceVariant
    val target = ringProgress(score)
    val sweep = remember { Animatable(NO_SWEEP) }
    LaunchedEffect(score) {
        sweep.animateTo(target, tween(SWEEP_TWEEN_MILLIS))
    }
    Box(
        modifier = modifier
            .size(diameter)
            .semantics { contentDescription = "得分 ${score.toInt()} 分" },
        contentAlignment = Alignment.Center
    ) {
        Canvas(modifier = Modifier.size(diameter)) {
            // 描边居中画在路径上: 不内缩半个线宽, 外沿就会被画布切掉半个环。
            val strokePx = strokeWidth.toPx()
            val inset = strokePx / STROKE_INSET_DIVISOR
            val arcSize = Size(size.width - strokePx, size.height - strokePx)
            val arcTopLeft = Offset(inset, inset)
            val arcStyle = Stroke(width = strokePx, cap = StrokeCap.Round)
            drawArc(
                color = trackColor,
                startAngle = RING_START_ANGLE,
                sweepAngle = RING_FULL_SWEEP,
                useCenter = false,
                topLeft = arcTopLeft,
                size = arcSize,
                style = arcStyle
            )
            drawArc(
                color = bandColor,
                startAngle = RING_START_ANGLE,
                sweepAngle = RING_FULL_SWEEP * sweep.value,
                useCenter = false,
                topLeft = arcTopLeft,
                size = arcSize,
                style = arcStyle
            )
        }
        Text(
            text = score.toInt().toString(),
            style = MaterialTheme.typography.titleLarge,
            fontWeight = FontWeight.Bold,
            color = bandColor,
            // 满分是三位数, 而这一环有两档尺寸(默认 56dp / 自由对话 40dp)。让它折行会把
            // "100"切成两行压在环上; 宁可让它按标题字号略微超出环的内沿 —— 环画在文字
            // 底下, 描边又是圆头, 超出的那点宽度不会撞到任何东西。
            maxLines = SCORE_TEXT_MAX_LINES,
            softWrap = false,
            overflow = TextOverflow.Visible
        )
    }
}

/**
 * 得分 → 环的扫过比例(100 分制)。
 *
 * NaN 要单独挡: `Double.coerceIn` 靠 `<` / `>` 判断, 而 NaN 的比较恒为假, 会原样漏出去,
 * 换成分数上就是一个永远画不出来的环。
 */
private fun ringProgress(score: Double): Float {
    if (score.isNaN()) return NO_SWEEP
    return (score / SCORE_SCALE).coerceIn(MIN_PROGRESS, MAX_PROGRESS).toFloat()
}

private val RING_DIAMETER: Dp = 56.dp
private val RING_STROKE_WIDTH: Dp = 6.dp
private const val RING_START_ANGLE = -90f
private const val RING_FULL_SWEEP = 360f
private const val NO_SWEEP = 0f
private const val STROKE_INSET_DIVISOR = 2f
private const val SWEEP_TWEEN_MILLIS = 400
private const val SCORE_SCALE = 100.0
private const val MIN_PROGRESS = 0.0
private const val MAX_PROGRESS = 1.0
private const val SCORE_TEXT_MAX_LINES = 1
