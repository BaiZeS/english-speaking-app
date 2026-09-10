package com.app.english.ui.components

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.LinearEasing
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
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
 * 实时麦克风波形: 新采样从**右缘推入**, 整条向左滚, 每根条的高度是它自己那一帧的
 * 峰值 —— 这才叫波形。它替换掉的 `RecordingLevelIndicator`(已删)结构上做不到这件事:
 * 那是个阈值电平表(`threshold = (index+1)/barCount`, 点亮条共用同一个高度), 没有历史
 * 缓冲, 所以用户看到的就是"一根永远不会动的固定条"。
 *
 * 采样必须喂 `AudioRecorder.waveformFlow`, 即**未平滑**的逐帧峰值:
 * `AudioLevelMapping.DECAY=0.25` 从 1.0 落到 0.05 要 ~440 ms, 而说话 3-5 音节/秒, 拿
 * 平滑过的 `levelFlow` 画波形会把相邻音节糊成一坨。
 *
 * 整条动画只有**一个**浮点数 —— [Animatable] 的 `shift`(亚槽位移, 见
 * [WaveformGeometry.barLeft])。每个新采样到位时把它掰回 1 再用一帧时长线性回到 0:
 * 数组本身此刻整体左移一格, 这一格 snap 正好抵掉它, 所以无论录音线程到达是准时还是
 * 抖动, 屏幕上都是连续左移而不会跳格。25 Hz 采样 + 这一层插值 = 视觉连续滚动; 给 40
 * 根条各挂一个动画的重组成本不可接受。
 *
 * [presentation] 三态的理由见 [WaveformPresentation]: 收工后 FROZEN 仍画出**刚说完那
 * 一条**的形状(只是变淡, 见计划 P2 决策 2), 而 IDLE 连采样都不看 —— 录音器是单例,
 * 别的页面刚录完的那一条不是这一页的历史。
 */
@Composable
fun RecordingWaveform(
    samples: List<Float>,
    presentation: WaveformPresentation,
    modifier: Modifier = Modifier,
    height: Dp = 36.dp,
    barGap: Dp = 2.dp
) {
    val trackColor = MaterialTheme.colorScheme.surfaceVariant
    val normalColor = MaterialTheme.colorScheme.primary
    val hotColor = MaterialTheme.colorScheme.tertiary
    val clippingColor = MaterialTheme.colorScheme.error
    val description = waveformContentDescription(samples, presentation)
    val shift = remember { Animatable(0f) }
    LaunchedEffect(samples) {
        // 只有真的在录才补间: 冻结的那一帧是历史, 不该继续往左爬。
        if (presentation == WaveformPresentation.LIVE) {
            shift.snapTo(1f)
            shift.animateTo(0f, tween(SAMPLE_INTERVAL_MS, easing = LinearEasing))
        }
    }
    Canvas(
        modifier = modifier
            .fillMaxWidth()
            .height(height)
            .semantics { contentDescription = description }
    ) {
        if (samples.isEmpty()) return@Canvas
        val slot = WaveformGeometry.slotWidth(size.width, samples.size)
        val barWidth = WaveformGeometry.barWidth(slot, barGap.toPx())
        samples.forEachIndexed { index, level ->
            val left = WaveformGeometry.barLeft(index, slot, shift.value)
            if (WaveformGeometry.isCulled(left, barWidth, size.width)) return@forEachIndexed
            // IDLE: 忽略采样, 一律画等高底轨 —— 这一页还没有自己的波形可讲。
            val barLevel = if (presentation == WaveformPresentation.IDLE) 0f else level
            val band = WaveformGeometry.band(barLevel)
            val color = when (band) {
                WaveformBand.TRACK -> trackColor
                WaveformBand.NORMAL -> normalColor
                WaveformBand.HOT -> hotColor
                WaveformBand.CLIPPING -> clippingColor
            }
            val barHeight = WaveformGeometry.barHeight(size.height, barLevel)
            drawRoundRect(
                color = color,
                topLeft = Offset(left, WaveformGeometry.barTop(size.height, barHeight)),
                size = Size(barWidth, barHeight),
                cornerRadius = CornerRadius(minOf(barWidth / 2f, MAX_CORNER.toPx())),
                alpha = band.alpha(presentation)
            )
        }
    }
}

/**
 * `StateFlow` 变体: 在**叶子**组合项里 collect。
 *
 * 把 25 Hz 的采样提到页面级collect会让整页每 40 ms 重组一次 —— 录音页正是一边滚动
 * 字幕一边画波形的地方(影子跟读那一屏把整篇课文铺在一个可重组的列表里)。让最里层
 * 这一格自己 collect, 每帧重画的就只有这一个 Canvas。
 */
@Composable
fun RecordingWaveform(
    waveform: StateFlow<List<Float>>,
    presentation: WaveformPresentation,
    modifier: Modifier = Modifier,
    height: Dp = 36.dp,
    barGap: Dp = 2.dp
) {
    val samples by waveform.collectAsStateWithLifecycle()
    RecordingWaveform(
        samples = samples,
        presentation = presentation,
        modifier = modifier,
        height = height,
        barGap = barGap
    )
}

/** 条尖圆角上限: 槽位再窄也不会把条画成药丸。 */
private val MAX_CORNER: Dp = 4.dp

/**
 * 补间时长与录音器一帧的时长同源(640 样本 @ 16 kHz = 40 ms, 见
 * [AudioRecorder.FRAME_SAMPLES]): 两者一旦各走各的, 波形要么追不上采样, 要么每帧被
 * snap 打断。
 */
private const val SAMPLE_INTERVAL_MS =
    AudioRecorder.FRAME_SAMPLES * 1000 / AudioRecorder.SAMPLE_RATE

/**
 * 无障碍描述写成纯函数: 这是屏幕上唯一每 40 ms 变一次的读屏文案, 语义说错比不播更糟
 * —— 停录之后还播报"正在录音"就是在撒谎。
 */
fun waveformContentDescription(samples: List<Float>, presentation: WaveformPresentation): String =
    when {
        presentation == WaveformPresentation.IDLE -> "麦克风波形, 空闲"
        samples.isEmpty() -> "麦克风波形, 暂无采样"
        presentation == WaveformPresentation.LIVE && WaveformGeometry.isSilentFrame(samples) ->
            "正在录音, 还没拾到声音"
        presentation == WaveformPresentation.LIVE -> "正在录音, 音量波形向左滚动"
        else -> "刚刚这条录音的波形"
    }
