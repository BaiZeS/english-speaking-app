package com.app.english.ui.components

import kotlin.math.abs

/**
 * 实时声量脉冲条的几何与色带(纯 Kotlin, 不 import Compose —— 与被删的 WaveformGeometry
 * 同一套做法: 数学放这里用 JVM 单测钉住, [RecordingPulseMeter] 只负责画)。
 *
 * 它替换的是 v2.2.0 的滚动波形(`RecordingWaveform`/`WaveformHistory`, 均已删): 那条
 * strip 画 1.6 秒历史、40 根细条密密排开, 观感是"一条锯齿波浪线在滚"。v2.2.1 按用户
 * 反馈改成 [BAR_COUNT] 根随**当前音量**跳动的脉冲条 —— 系统录音机那种"声量波动"。
 * 数据源随之从"未平滑逐帧峰值"换成 [com.app.english.audio.AudioRecorder.levelFlow]
 * 的 VU 包络(ATTACK=0.7 / DECAY=0.25): "快起慢落"的手感就是这条包络本身, UI 层不再
 * 造第二套平滑。
 *
 * 三态语义与旧件同源(录音器是单例): LIVE 在录 / FROZEN 定格(刚送评分, 显示本条峰值) /
 * IDLE 空闲(忽略电平, 画淡底轨)。定格峰值由 [RecordingPulseMeter] 在组合态自己捕获
 * ([nextPeak]), 录音器不再持有任何历史。
 */
object PulseMeterGeometry {

    /** 脉冲条根数: 中心高、两端低的一小组。 */
    const val BAR_COUNT: Int = 5

    /** 对称轮廓的最低权重(边缘条相对中心条)。 */
    const val MIN_PROFILE_WEIGHT: Float = 0.55f

    /** 静音(level=0)时保留的细底, 让整组即使全静音也像"轨道"而不是空白。 */
    const val TROUGH_FRACTION: Float = 0.08f

    /** 低于此值按"无信号"处理: 涂底轨色而不是电平色。 */
    const val SILENT_LEVEL: Float = 0.001f

    /** 色带阈值沿用旧电平表: >0.85 红, >0.65 琥珀, 其余主色。 */
    const val CLIPPING_LEVEL: Float = 0.85f
    const val HOT_LEVEL: Float = 0.65f

    /** 定格帧(送评分中)的透明度: 峰值仍在, 但要说清"这不是实时电平"。 */
    const val FROZEN_ALPHA: Float = 0.42f

    /** 静音条/底轨的透明度(与旧组件同一观感)。 */
    const val TRACK_ALPHA: Float = 0.32f

    /**
     * 单一电平驱动整组时的分条权重: 离中心越远越矮, 线性衰减到 [MIN_PROFILE_WEIGHT]。
     * n=5 → [0.55, 0.775, 1, 0.775, 0.55]。没有这份轮廓, 5 根等高条只会像一块方块在
     * 整体缩放 —— "波动"感来自条与条之间的高度差。
     */
    fun profileWeight(index: Int, barCount: Int = BAR_COUNT): Float {
        require(barCount >= 3) { "barCount 至少 3, 否则没有\"中间高两端低\"可言" }
        require(index in 0 until barCount) { "index 越界: $index / $barCount" }
        val center = (barCount - 1) / 2f
        val distance = abs(index - center) / center
        return 1f - distance * (1f - MIN_PROFILE_WEIGHT)
    }

    /**
     * 单条高度(px): [level] 已是"该条自己的目标电平"(调用方把共享电平乘过
     * [profileWeight]), [weight] 保留为 1 之外的缩放入口。NaN 按 0 处理: NaN 高度会让
     * Compose 整层不画, 表现成"脉冲条忽然消失"。
     */
    fun barHeight(canvasHeightPx: Float, level: Float, weight: Float): Float {
        val clamped = if (level.isNaN()) 0f else level.coerceIn(0f, 1f)
        val safeWeight = if (weight.isNaN()) 0f else weight.coerceIn(0f, 1f)
        return canvasHeightPx * (TROUGH_FRACTION + clamped * safeWeight * (1f - TROUGH_FRACTION))
    }

    /** 上下居中的顶边(px): 脉冲条以中线为轴镜像, 而不是从底部往上长。 */
    fun barTop(canvasHeightPx: Float, heightPx: Float): Float = (canvasHeightPx - heightPx) / 2f

    /** 居中条组的总宽(px)。 */
    fun groupWidth(count: Int, barWidthPx: Float, gapPx: Float): Float =
        count * barWidthPx + (count - 1).coerceAtLeast(0) * gapPx

    /**
     * 第 [index] 根条的左边界(px): 整组在画布里水平居中; 画布比条组还窄时贴左缘,
     * 超出右缘的部分交给画布裁剪。
     */
    fun barLeft(
        index: Int,
        canvasWidthPx: Float,
        barWidthPx: Float,
        gapPx: Float,
        count: Int = BAR_COUNT
    ): Float {
        val groupLeft = maxOf(0f, (canvasWidthPx - groupWidth(count, barWidthPx, gapPx)) / 2f)
        return groupLeft + index * (barWidthPx + gapPx)
    }

    /**
     * 定格峰值的累进: 取历史最大。存在理由是收工竞态 —— `AudioRecorder.finalizeTake`
     * 先把电平清零、UI 的 isBusy 后翻转, 于是 FROZEN 之前电平流上会掠过一串 0;
     * `nextPeak(0.6f, 0f) == 0.6f` 保证峰值不被那串 0 偷走。NaN/负数当 0, 入参一律
     * clamp 回 0..1(脏数据不许画出爆表条)。
     */
    fun nextPeak(peak: Float, level: Float): Float {
        val base = if (peak.isNaN() || peak < 0f) 0f else peak.coerceAtMost(1f)
        val incoming = if (level.isNaN() || level < 0f) 0f else level.coerceAtMost(1f)
        return maxOf(base, incoming)
    }

    /** 这一帧是不是没拾到声音(用来区分"在录但没出声"和"在录且在说")。 */
    fun isSilent(level: Float): Boolean = level.isNaN() || level <= SILENT_LEVEL

    /** 当前电平的色带。NaN/负值按静音处理, 不让脏数据画出"爆表红"。 */
    fun band(level: Float): PulseBand = when {
        level.isNaN() || level <= SILENT_LEVEL -> PulseBand.TRACK
        level > CLIPPING_LEVEL -> PulseBand.CLIPPING
        level > HOT_LEVEL -> PulseBand.HOT
        else -> PulseBand.NORMAL
    }

    /**
     * 这一组脉冲该以什么身份画。三态而不是一个布尔, 理由与旧件一致: `AudioRecorder`
     * 是单例, 只看"现在没在录"会把别的页面的状态误当自己的。IDLE 下电平一律忽略。
     */
    fun presentation(isRecording: Boolean, isBusy: Boolean): PulsePresentation = when {
        isRecording -> PulsePresentation.LIVE
        isBusy -> PulsePresentation.FROZEN
        else -> PulsePresentation.IDLE
    }
}

/** 一根脉冲条的色带归属; 具体色值由调用方从 `ColorScheme` 取(主题只能在组合期拿)。 */
enum class PulseBand {
    /** 无信号 —— 画底轨。 */
    TRACK,

    /** 正常语音量。 */
    NORMAL,

    /** 偏大(> [PulseMeterGeometry.HOT_LEVEL])。 */
    HOT,

    /** 削顶风险(> [PulseMeterGeometry.CLIPPING_LEVEL])。 */
    CLIPPING
}

/** 一组脉冲的身份: 在录 / 定格(刚送评分, 显示峰值) / 空闲(画淡底轨, 忽略电平)。 */
enum class PulsePresentation { LIVE, FROZEN, IDLE }

/**
 * 色带 -> 透明度: 底轨永远低透明; 有信号的条在定格态降到 [PulseMeterGeometry.FROZEN_ALPHA],
 * 而 IDLE 下根本不该出现(调用方已把电平当 0 处理), 这里给个兜底免得画出实时亮度的残影。
 */
fun PulseBand.alpha(presentation: PulsePresentation): Float = when (this) {
    PulseBand.TRACK -> PulseMeterGeometry.TRACK_ALPHA
    else -> when (presentation) {
        PulsePresentation.LIVE -> 1f
        PulsePresentation.FROZEN -> PulseMeterGeometry.FROZEN_ALPHA
        PulsePresentation.IDLE -> PulseMeterGeometry.TRACK_ALPHA
    }
}

/**
 * 读屏文案写成纯函数: 这是屏幕上唯一每 40 ms 变一次的读屏文案, 语义说错比不播更糟。
 * 诚实规则与旧件同源: 停录之后绝不再播报"正在录音"; 脉冲条不滚动, 文案也不再提
 * "滚/波形"。定格态区分"有条录音"与"整条全静音" —— 后者给"峰值 0"是假读数。
 */
fun pulseContentDescription(presentation: PulsePresentation, level: Float, peak: Float): String =
    when {
        presentation == PulsePresentation.IDLE -> "音量脉冲, 空闲"
        presentation == PulsePresentation.LIVE && PulseMeterGeometry.isSilent(level) ->
            "正在录音, 还没拾到声音"
        presentation == PulsePresentation.LIVE -> "正在录音, 音量脉冲随说话跳动"
        PulseMeterGeometry.isSilent(peak) -> "刚刚那条录音, 没有拾到声音"
        else -> "刚刚那条录音的峰值音量"
    }
