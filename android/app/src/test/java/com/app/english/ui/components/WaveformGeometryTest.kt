package com.app.english.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * [WaveformGeometry] 的纯数学契约 —— 也就是"这根条到底会不会滚"的那部分。
 *
 * 用户报的"录音条固定不动"根因是旧组件没有历史缓冲; 有了缓冲之后, 唯一还能把它画成
 * "不动"的地方就是槽位数学。[barLeft] 里那个 `- GUTTER_SLOTS` 正是把"新样本推入"这一
 * 格跳变摊平成连续左移的项, 所以第一条测试钉的就是连续性: 它挂了就等于退化成"整条每
 * 隔 40 ms 跳一格"。
 */
class WaveformGeometryTest {

    private fun Float.d() = toDouble()

    @Test
    fun pushKeepsEveryBarAtItsPreviousPixelPosition() {
        val slot = WaveformGeometry.slotWidth(CANVAS, SAMPLES)
        // 推入前: 某根样本在下标 7、shift=0(上一帧已落位)。
        val before = WaveformGeometry.barLeft(7, slot, 0f)
        // 推入后: 同一根样本的下标变成 6, 而 shift 被掰回 1 —— 像素必须一模一样。
        val after = WaveformGeometry.barLeft(6, slot, 1f)
        assertEquals(before.d(), after.d(), 1e-4)
    }

    @Test
    fun shiftDrivesTheWholeStripLeftByExactlyOneSlot() {
        val slot = WaveformGeometry.slotWidth(CANVAS, SAMPLES)
        val atPush = WaveformGeometry.barLeft(20, slot, 1f)
        val settled = WaveformGeometry.barLeft(20, slot, 0f)
        assertEquals(slot.d(), (atPush - settled).d(), 1e-4)
        assertTrue("shift 越大越靠右, 也就是条在向左滚", atPush > settled)
    }

    @Test
    fun newestBarRestsInsideTheRightEdgeAndOldestRestsOffTheLeft() {
        val gap = 2f
        val slot = WaveformGeometry.slotWidth(CANVAS, SAMPLES)
        val barWidth = WaveformGeometry.barWidth(slot, gap)
        val newestLeft = WaveformGeometry.barLeft(SAMPLES - 1, slot, 0f)
        // 落位(shift=0): 最新一条的右边界 = 右缘往内一个 gap, 且不该被裁掉。
        assertEquals((CANVAS - gap).d(), (newestLeft + barWidth).d(), 1e-3)
        assertFalse(WaveformGeometry.isCulled(newestLeft, barWidth, CANVAS))
        // 落位时最旧一条整个在左缘之外(正滑出): 可见的是 39 根而不是 40 根。
        val oldestLeft = WaveformGeometry.barLeft(0, slot, 0f)
        assertTrue(WaveformGeometry.isCulled(oldestLeft, barWidth, CANVAS))
    }

    @Test
    fun barsEnterFromOffTheRightAndExitOffTheLeftDuringTheSlide() {
        val slot = WaveformGeometry.slotWidth(CANVAS, SAMPLES)
        val barWidth = WaveformGeometry.barWidth(slot, 2f)
        // shift=1(刚推入): 最新一条整个在右缘之外 -> 被裁 -> 观感上是"从右缘推入"。
        val entering = WaveformGeometry.barLeft(SAMPLES - 1, slot, 1f)
        // 用 >= width - 1f 而不是精确 isCulled: 除不尽的槽宽让右边界落在 399.99998f,
        // 而"贴边但只差一像素"本来就该照画(它本来就不可见), 把它精确裁掉反而是脆的。
        assertTrue("推入瞬间最新一条应贴在右缘(几乎裁到不可见)", entering >= CANVAS - 1f)
        // 刚推入时最旧一条整个可见, 随后滑向左缘 —— 两帧之间没有"整条左跳一格"。
        val sliding = WaveformGeometry.barLeft(0, slot, 1f)
        assertFalse(WaveformGeometry.isCulled(sliding, barWidth, CANVAS))
        assertEquals(0.0, sliding.d(), 1e-3)
    }

    @Test
    fun degenerateSampleCountsNeverDivideByZero() {
        assertEquals(CANVAS.d(), WaveformGeometry.slotWidth(CANVAS, 1).d(), 1e-4)
        assertEquals(CANVAS.d(), WaveformGeometry.slotWidth(CANVAS, 0).d(), 1e-4)
        assertEquals(CANVAS.d(), WaveformGeometry.slotWidth(CANVAS, -3).d(), 1e-4)
        assertTrue(WaveformGeometry.slotWidth(CANVAS, SAMPLES) > 0f)
    }

    @Test
    fun eachBarHeightComesFromItsOwnSampleOnly() {
        val height = 120f
        val loud = WaveformGeometry.barHeight(height, 0.9f)
        val quiet = WaveformGeometry.barHeight(height, 0.1f)
        assertTrue("每根条必须按自己的采样取值, 否则又变回共用一个高度的电平表", loud > quiet)
        assertEquals(height.d(), WaveformGeometry.barHeight(height, 1f).d(), 1e-4)
    }

    @Test
    fun silenceKeepsAVisibleStubAndGarbageNeverOverflowsTheCanvas() {
        val height = 120f
        assertEquals(
            (WaveformGeometry.TROUGH_FRACTION * height).d(),
            WaveformGeometry.barHeight(height, 0f).d(),
            1e-4
        )
        assertTrue(WaveformGeometry.barHeight(height, -5f) >= 0f)
        assertEquals(height, WaveformGeometry.barHeight(height, Float.POSITIVE_INFINITY))
        // NaN 高度会让 Compose 整层不画, 表现恰恰就是"波形忽然消失"。
        assertFalse(WaveformGeometry.barHeight(height, Float.NaN).isNaN())
        assertFalse(
            WaveformGeometry.barTop(height, WaveformGeometry.barHeight(height, Float.NaN)).isNaN()
        )
    }

    @Test
    fun colourBandsKeepTheOldMeterThresholds() {
        assertEquals(WaveformBand.NORMAL, WaveformGeometry.band(0.5f))
        assertEquals(WaveformBand.NORMAL, WaveformGeometry.band(WaveformGeometry.HOT_LEVEL))
        assertEquals(WaveformBand.HOT, WaveformGeometry.band(0.66f))
        assertEquals(WaveformBand.HOT, WaveformGeometry.band(WaveformGeometry.CLIPPING_LEVEL))
        assertEquals(WaveformBand.CLIPPING, WaveformGeometry.band(0.86f))
        assertEquals(WaveformBand.TRACK, WaveformGeometry.band(0f))
        assertEquals("脏值不许被涂成爆表红", WaveformBand.TRACK, WaveformGeometry.band(Float.NaN))
    }

    @Test
    fun frozenTakeIsDimmedButStillDrawsItsShape() {
        assertEquals(1f, WaveformBand.NORMAL.alpha(WaveformPresentation.LIVE), 0f)
        val frozen = WaveformBand.NORMAL.alpha(WaveformPresentation.FROZEN)
        assertTrue(
            "冻结帧仍要画出来(只是变淡), 所以 alpha 必须落在 0 与实时之间",
            frozen in 0.05f..0.95f
        )
        // 静音条在任何身份下都是底轨透明度: 空闲态就是"一根低透明度的平轨"。
        for (presentation in WaveformPresentation.entries) {
            assertEquals(
                "presentation=$presentation",
                WaveformGeometry.TRACK_ALPHA,
                WaveformBand.TRACK.alpha(presentation),
                0f
            )
        }
    }

    @Test
    fun presentationSeparatesLiveFrozenAndIdle() {
        assertEquals(WaveformPresentation.LIVE, WaveformGeometry.presentation(true, false))
        // 在录优先于在途: 自动送评的那一帧仍然该是活的。
        assertEquals(WaveformPresentation.LIVE, WaveformGeometry.presentation(true, true))
        assertEquals(WaveformPresentation.FROZEN, WaveformGeometry.presentation(false, true))
        assertEquals(WaveformPresentation.IDLE, WaveformGeometry.presentation(false, false))
    }

    @Test
    fun silentFrameDetectionMatchesWhatTheRecorderEmitsWhileIdle() {
        assertTrue(WaveformGeometry.isSilentFrame(List(SAMPLES) { 0f }))
        assertTrue(WaveformGeometry.isSilentFrame(emptyList()))
        assertFalse(WaveformGeometry.isSilentFrame(List(SAMPLES) { if (it == 30) 0.4f else 0f }))
        // NaN 与 [band] 的口径一致: 脏值既不该画成爆表红, 也不该在描述里谎称"这帧有声"。
        assertTrue(WaveformGeometry.isSilentFrame(listOf(Float.NaN, 0f)))
    }

    @Test
    fun barWidthNeverGoesNegativeWhenGapOutweighsSlot() {
        val slot = WaveformGeometry.slotWidth(CANVAS, SAMPLES)
        assertEquals(0f, WaveformGeometry.barWidth(slot, slot * 10f), 0f)
    }

    @Test
    fun contentDescriptionTellsLiveFrozenAndIdleApart() {
        val loud = List(SAMPLES) { if (it > 30) 0.5f else 0f }
        val quiet = List(SAMPLES) { 0f }
        val live = waveformContentDescription(loud, WaveformPresentation.LIVE)
        assertTrue(live.contains("正在录音"))
        assertTrue("活的一帧必须说清它在滚, 这正是用户抱怨的反面", live.contains("滚"))
        // 关键诚实性: 停录之后绝不许再播报"正在录音"。
        val frozen = waveformContentDescription(loud, WaveformPresentation.FROZEN)
        assertFalse(frozen.contains("正在录音"))
        assertTrue(frozen.contains("刚刚"))
        assertTrue(waveformContentDescription(quiet, WaveformPresentation.IDLE).contains("空闲"))
        assertTrue(
            waveformContentDescription(quiet, WaveformPresentation.LIVE).contains("还没拾到声音")
        )
        assertTrue(waveformContentDescription(emptyList(), WaveformPresentation.LIVE).contains("暂无采样"))
    }

    private companion object {
        const val CANVAS = 400f
        const val SAMPLES = 40
    }
}
