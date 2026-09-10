package com.app.english.ui.components

/**
 * 滚动波形的几何与色带(纯 Kotlin, 不 import Compose —— 与 [RadarGeometry] 同一套做法:
 * 数学放这里用 JVM 单测钉住, [RecordingWaveform] 只负责画)。
 *
 * 一条 `samples`(oldest→newest, 由 `WaveformHistory.snapshot()` 给出)被画成
 * `samples.size` 根条, 但**可见槽位只有 `samples.size - GUTTER_SLOTS` 个**: 最左那一格
 * 是"滑出画布"的缓冲区。理由藏在连续性里 —— 新样本推进来的瞬间数组整体左移一格, 于是
 * "旧下标 j 在 shift=0 的位置" 必须等于 "新下标 j-1 在 shift=1 的位置", 整条才不会
 * 跳变。[barLeft] 里那个 `- GUTTER_SLOTS` 就是让这个等式成立的那一项: 它使最旧一根条在
 * shift→0 时滑到 `-slot`(被画布裁掉, 观感上就是从左缘滑出去), 最新一根在 shift=1 时落
 * 在右缘之外(观感上就是从右缘推进来)。两侧都是**连续滑出/滑入**, 所以既不需要额外淡变,
 * 也不会在边上留下按帧闪烁的空槽。
 */
object WaveformGeometry {

    /** 最左槽位只当出画缓冲用(见文件注释), 可见槽位数 = `sampleCount - GUTTER_SLOTS`。 */
    const val GUTTER_SLOTS: Int = 1

    /** 静音(level=0)时保留的细底, 让整条即使全静音也像"轨道"而不是空白。 */
    const val TROUGH_FRACTION: Float = 0.08f

    /** 低于此值按"无信号"处理: 涂底轨色而不是电平色。 */
    const val SILENT_LEVEL: Float = 0.001f

    /** 色带阈值沿用旧阈值电平表: >0.85 红, >0.65 琥珀, 其余主色。 */
    const val CLIPPING_LEVEL: Float = 0.85f
    const val HOT_LEVEL: Float = 0.65f

    /** 冻结帧(送评分中)的透明度: 形状保留, 但要说清"这不是实时电平"。 */
    const val FROZEN_ALPHA: Float = 0.42f

    /** 静音条的底轨透明度(与旧组件同一观感)。 */
    const val TRACK_ALPHA: Float = 0.32f

    /** 一个槽位的宽度; 采样少到铺不开时退回整宽, 不除零。 */
    fun slotWidth(canvasWidth: Float, sampleCount: Int): Float {
        val slots = sampleCount - GUTTER_SLOTS
        return if (slots <= 0) canvasWidth else canvasWidth / slots
    }

    /**
     * 第 [index] 根条(0 = 最旧)的左边界。[shift] 是整条**唯一**的动画量: 1 = 刚推入
     * 一格, 0 = 落位; 条向左滚, 所以 `shift` 随时间递减。
     */
    fun barLeft(index: Int, slot: Float, shift: Float): Float =
        (index + shift - GUTTER_SLOTS) * slot

    /** 条宽 = 槽宽 - 间隙; gap 传大了也不会画出负宽度。 */
    fun barWidth(slot: Float, gap: Float): Float = (slot - gap).coerceAtLeast(0f)

    /** 完全在画布外的条直接跳过。 */
    fun isCulled(left: Float, width: Float, canvasWidth: Float): Boolean =
        left + width <= 0f || left >= canvasWidth

    /**
     * 单条高度(px): 每根条**只**按自己的采样取值 —— 这正是"波形"区别于电平表的地方。
     * NaN 按 0 处理: NaN 高度会让 Compose 整层不画, 表现成"波形忽然消失"。
     */
    fun barHeight(canvasHeight: Float, level: Float): Float {
        val clamped = if (level.isNaN()) 0f else level.coerceIn(0f, 1f)
        return canvasHeight * (TROUGH_FRACTION + clamped * (1f - TROUGH_FRACTION))
    }

    /** 上下居中的顶边(px): 波形以中线为轴镜像, 而不是从底部往上长。 */
    fun barTop(canvasHeight: Float, height: Float): Float = (canvasHeight - height) / 2f

    /** 这一帧是不是全静音(用来区分"在录但没出声"和"在录且在说")。 */
    fun isSilentFrame(samples: List<Float>): Boolean =
        samples.all { it.isNaN() || it <= SILENT_LEVEL }

    /** 单条色带。NaN/负值按静音处理, 不让脏数据画出"爆表红"。 */
    fun band(level: Float): WaveformBand = when {
        level.isNaN() || level <= SILENT_LEVEL -> WaveformBand.TRACK
        level > CLIPPING_LEVEL -> WaveformBand.CLIPPING
        level > HOT_LEVEL -> WaveformBand.HOT
        else -> WaveformBand.NORMAL
    }

    /**
     * 这一格波形该以什么身份画。三态而不是一个布尔, 是因为 `AudioRecorder` 是单例、
     * 窗口又按 P2 决策 2 **收工不清** —— 只看"现在没在录"的屏会把**别的页面**刚录完
     * 的那一条误当成自己的历史画出来。IDLE 就是为此存在: 本页面没有自己的录音可讲时,
     * 采样一律忽略。
     */
    fun presentation(isRecording: Boolean, isBusy: Boolean): WaveformPresentation = when {
        isRecording -> WaveformPresentation.LIVE
        isBusy -> WaveformPresentation.FROZEN
        else -> WaveformPresentation.IDLE
    }
}

/** 一条采样柱的色带归属; 具体色值由调用方从 `ColorScheme` 取(主题只能在组合期拿)。 */
enum class WaveformBand {
    /** 无信号(或刚被清零)—— 画底轨。 */
    TRACK,

    /** 正常语音量。 */
    NORMAL,

    /** 偏大(> [WaveformGeometry.HOT_LEVEL])。 */
    HOT,

    /** 削顶风险(> [WaveformGeometry.CLIPPING_LEVEL])。 */
    CLIPPING
}

/** 一帧波形的身份: 在录 / 冻结(刚送评分, 形状保留) / 空闲(只画平轨, 忽略采样)。 */
enum class WaveformPresentation { LIVE, FROZEN, IDLE }

/**
 * 色带 -> 透明度: 底轨永远低透明; 有信号的条在冻结态降到 [WaveformGeometry.FROZEN_ALPHA],
 * 而在 IDLE 下根本不该出现(调用方已把采样当 0 处理), 这里给个兜底免得画出实时亮度的残影。
 */
fun WaveformBand.alpha(presentation: WaveformPresentation): Float = when (this) {
    WaveformBand.TRACK -> WaveformGeometry.TRACK_ALPHA
    else -> when (presentation) {
        WaveformPresentation.LIVE -> 1f
        WaveformPresentation.FROZEN -> WaveformGeometry.FROZEN_ALPHA
        WaveformPresentation.IDLE -> WaveformGeometry.TRACK_ALPHA
    }
}
