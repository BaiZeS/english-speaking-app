package com.app.english.ui.components

import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.snap
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.semantics.contentDescription
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.audio.AudioRecorder
import kotlinx.coroutines.flow.StateFlow

/**
 * 实时声量脉冲条: 5 根圆角条跟着**当前麦克风音量**跳动, 替换掉 v2.2.0 的滚动波形
 * 组件(已删, 来历见 [PulseMeterGeometry] 的注释) —— 那条锯齿波浪线读不出"我现在
 * 声量多大", 用户要的观感是系统录音机那种声量脉冲。几何与色带全部钉在
 * [PulseMeterGeometry](纯 Kotlin + JVM 单测), 这里只负责画。
 *
 * 数据源换成了 [AudioRecorder.levelFlow] 的平滑 VU 包络: "快起慢落"的手感就是包络
 * 本身, UI 层不再造第二套平滑。代价是源头不再有历史 —— **定格**显示因此是本组合项
 * 自己的职责: LIVE 期间用 [PulseMeterGeometry.nextPeak] 累进运行最大值到 peak, FROZEN
 * 画 peak。清零时机有个竞态: [AudioRecorder.finalizeTake] 在 UI 的 isBusy 翻位**之前**
 * 就把电平归零, 松手到送评之间还会掠过一帧瞬时的 IDLE, 于是 FROZEN 到达前电平流上
 * 已经有一串 0。peak 若在离开 LIVE 时清, 就是被那串瞬时帧偷走峰值、定格只剩底轨 ——
 * 所以只在**进入 LIVE** 时清零(新一段开录, 这一条从头算起), 并配合 FROZEN/IDLE 的
 * snap() (晚到的 0 发射不许把定格条动画下去)。
 *
 * `StateFlow` 在**叶子**里 collect(不升进 UiState): 录音页同时在滚字幕、翻状态,
 * 25 Hz 的整屏重组是白扔的帧; 这里电平每变一帧, 重画的只有这一个 Canvas。
 */
@Composable
fun RecordingPulseMeter(
    level: StateFlow<Float>,
    presentation: PulsePresentation,
    modifier: Modifier = Modifier,
    height: Dp = 36.dp,
    barWidth: Dp = 5.dp,
    barGap: Dp = 7.dp
) {
    val levelValue by level.collectAsStateWithLifecycle()

    var peak by remember { mutableFloatStateOf(0f) }
    LaunchedEffect(presentation) {
        // 只在进入 LIVE 时清零, 绝不在离开时清 —— 见文件注释的收工竞态。
        if (presentation == PulsePresentation.LIVE) peak = 0f
    }
    LaunchedEffect(presentation, levelValue) {
        if (presentation == PulsePresentation.LIVE) {
            peak = PulseMeterGeometry.nextPeak(peak, levelValue)
        }
    }

    val driver = when (presentation) {
        PulsePresentation.LIVE -> levelValue
        PulsePresentation.FROZEN -> peak
        PulsePresentation.IDLE -> 0f
    }

    // 每根条一个补间: 目标 = 共享 driver × 自己的轮廓权重(中心高两端低, 波动感来自
    // 条间高度差)。LIVE 用一帧时长线性补间(25 Hz 刷新, 不超调); FROZEN/IDLE 一律
    // snap() —— 定格不是动画, 一串晚到的 0 发射更不能把定格的条"降"回底轨。
    val shapedLevels = (0 until PulseMeterGeometry.BAR_COUNT).map { index ->
        animateFloatAsState(
            targetValue = driver * PulseMeterGeometry.profileWeight(index),
            animationSpec = if (presentation == PulsePresentation.LIVE) {
                tween(FRAME_MS, easing = LinearEasing)
            } else {
                snap()
            },
            label = "pulseBar$index"
        )
    }

    // 色带按**共享 driver** 整体判一次, 不是逐条判: 5 条各自为政会让边缘条还是
    // TRACK 而中心已 NORMAL, 整组观感花掉。IDLE 已在 driver 里归零, 这里再兜一次底。
    val band = PulseMeterGeometry.band(if (presentation == PulsePresentation.IDLE) 0f else driver)
    val bandColor = when (band) {
        PulseBand.TRACK -> MaterialTheme.colorScheme.surfaceVariant
        PulseBand.NORMAL -> MaterialTheme.colorScheme.primary
        PulseBand.HOT -> MaterialTheme.colorScheme.tertiary
        PulseBand.CLIPPING -> MaterialTheme.colorScheme.error
    }
    val bandAlpha = band.alpha(presentation)
    val description = pulseContentDescription(presentation, levelValue, peak)

    Canvas(
        // clipToBounds: 画布比条组窄时最右条会出界, 必须裁掉(同旧波形组件的处理)。
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .clipToBounds()
            .semantics { contentDescription = description }
    ) {
        val barWidthPx = barWidth.toPx()
        val gapPx = barGap.toPx()
        shapedLevels.forEachIndexed { index, shaped ->
            val left = PulseMeterGeometry.barLeft(index, size.width, barWidthPx, gapPx)
            // shaped 的值在绘制期读取: 补间每一帧只重跑绘制, 不额外掀整段重组。
            val barHeightPx = PulseMeterGeometry.barHeight(size.height, shaped.value, 1f)
            drawRoundRect(
                color = bandColor,
                topLeft = Offset(left, PulseMeterGeometry.barTop(size.height, barHeightPx)),
                size = Size(barWidthPx, barHeightPx),
                cornerRadius = CornerRadius(minOf(barWidthPx / 2f, MAX_CORNER.toPx())),
                alpha = bandAlpha
            )
        }
    }
}

/** 条尖圆角上限: 条再窄也不会把脉冲画成药丸(与旧波形组件同一观感)。 */
private val MAX_CORNER: Dp = 4.dp

/**
 * 补间时长与录音器一帧的时长同源(640 样本 @ 16 kHz = 40 ms, 见
 * [AudioRecorder.FRAME_SAMPLES]): 电平每帧才更新一次, 补间再快也只是空转。
 */
private const val FRAME_MS = AudioRecorder.FRAME_SAMPLES * 1000 / AudioRecorder.SAMPLE_RATE
