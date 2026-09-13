package com.app.english.ui.components

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 脉冲条几何与定格峰值的 JVM 钉子。滚动波形的 8 个连续性/滑移测试随 strip 一起删了
 * (脉冲条没有"滚动"这件事可测); band/alpha/presentation/诚实文案按原语义迁移。
 */
class PulseMeterGeometryTest {

    private val canvas = 400f

    // ---- presentation: 三态身份 ----

    @Test
    fun presentationSeparatesLiveFrozenAndIdle() {
        assertEquals(
            PulsePresentation.LIVE,
            PulseMeterGeometry.presentation(isRecording = true, isBusy = false)
        )
        assertEquals(
            PulsePresentation.FROZEN,
            PulseMeterGeometry.presentation(isRecording = false, isBusy = true)
        )
        assertEquals(
            PulsePresentation.IDLE,
            PulseMeterGeometry.presentation(isRecording = false, isBusy = false)
        )
        // 在录优先于在途: 录音键按住时永远是 LIVE。
        assertEquals(
            PulsePresentation.LIVE,
            PulseMeterGeometry.presentation(isRecording = true, isBusy = true)
        )
    }

    // ---- band / alpha: 色带与透明度 ----

    @Test
    fun colourBandsKeepTheMeterThresholds() {
        assertEquals(PulseBand.NORMAL, PulseMeterGeometry.band(0.5f))
        assertEquals(PulseBand.HOT, PulseMeterGeometry.band(PulseMeterGeometry.HOT_LEVEL + 0.01f))
        assertEquals(
            PulseBand.NORMAL,
            PulseMeterGeometry.band(PulseMeterGeometry.HOT_LEVEL)
        )
        assertEquals(
            PulseBand.CLIPPING,
            PulseMeterGeometry.band(PulseMeterGeometry.CLIPPING_LEVEL + 0.01f)
        )
        assertEquals(
            PulseBand.HOT,
            PulseMeterGeometry.band(PulseMeterGeometry.CLIPPING_LEVEL)
        )
    }

    @Test
    fun dirtyLevelsMapToTheTrackBand() {
        assertEquals(PulseBand.TRACK, PulseMeterGeometry.band(0f))
        assertEquals(PulseBand.TRACK, PulseMeterGeometry.band(-1f))
        assertEquals(PulseBand.TRACK, PulseMeterGeometry.band(Float.NaN))
        // +Inf 与旧电平表同语义: 高度层会 clamp, 色带层只防 NaN 这一种脏值。
        assertEquals(PulseBand.CLIPPING, PulseMeterGeometry.band(Float.POSITIVE_INFINITY))
    }

    @Test
    fun frozenPulseIsDimmedButStillDrawn() {
        val frozen = PulseBand.NORMAL.alpha(PulsePresentation.FROZEN)
        assertTrue("定格要降透明度", frozen < 1f)
        assertTrue("定格不能淡到看不见", frozen in 0.05f..0.95f)
        assertEquals(1f, PulseBand.NORMAL.alpha(PulsePresentation.LIVE), 0f)
    }

    @Test
    fun trackBandStaysFaintUnderEveryPresentation() {
        PulsePresentation.values().forEach { presentation ->
            assertEquals(
                PulseMeterGeometry.TRACK_ALPHA,
                PulseBand.TRACK.alpha(presentation),
                0f
            )
        }
    }

    // ---- barHeight: 细底、夹取与 NaN 防御 ----

    @Test
    fun silentBarsKeepAVisibleStubAndGarbageNeverOverflows() {
        val stub = PulseMeterGeometry.barHeight(canvas, 0f, 1f)
        assertEquals(canvas * PulseMeterGeometry.TROUGH_FRACTION, stub, 0.001f)
        // 负电平夹回细底, 超满电平夹回满高 —— 不许画出画布。
        assertEquals(stub, PulseMeterGeometry.barHeight(canvas, -3f, 1f), 0.001f)
        assertEquals(canvas, PulseMeterGeometry.barHeight(canvas, 1.7f, 1f), 0.001f)
        // NaN 电平/NaN 权重都退到有限值: NaN 高度会让 Compose 整层不画。
        assertFalse(PulseMeterGeometry.barHeight(canvas, Float.NaN, 1f).isNaN())
        assertFalse(PulseMeterGeometry.barHeight(canvas, 0.6f, Float.NaN).isNaN())
        assertFalse(
            PulseMeterGeometry.barTop(canvas, PulseMeterGeometry.barHeight(canvas, Float.NaN, 1f))
                .isNaN()
        )
    }

    // ---- profileWeight: 中心峰、镜像对称 ----

    @Test
    fun profileIsCentrePeakedAndMirrorSymmetric() {
        val n = PulseMeterGeometry.BAR_COUNT
        val weights = (0 until n).map { PulseMeterGeometry.profileWeight(it) }
        assertEquals(1f, PulseMeterGeometry.profileWeight(n / 2), 0f)
        weights.forEachIndexed { index, weight ->
            assertEquals(
                "轮廓必须左右镜像",
                PulseMeterGeometry.profileWeight(n - 1 - index),
                weight,
                0f
            )
            assertTrue("权重必须落在 (0, 1]", weight in 0f..1f)
        }
        assertEquals(
            PulseMeterGeometry.MIN_PROFILE_WEIGHT,
            weights.first(),
            0.001f
        )
        // 同一电平下中心条必须真的比边缘条高 —— 否则整组是块缩放的方块。
        val centre = PulseMeterGeometry.barHeight(canvas, 0.8f, weights[n / 2])
        val edge = PulseMeterGeometry.barHeight(canvas, 0.8f, weights.first())
        assertTrue(centre > edge)
    }

    @Test
    fun barHeightsScaleWithLevelAndProfileMonotonically() {
        val weight = PulseMeterGeometry.profileWeight(PulseMeterGeometry.BAR_COUNT / 2)
        val quiet = PulseMeterGeometry.barHeight(canvas, 0.2f, weight)
        val loud = PulseMeterGeometry.barHeight(canvas, 0.8f, weight)
        assertTrue("电平越大条越高", loud > quiet)
        // 满电平 × 满权重 = 满画布高(否则又成了阈值电平表)。
        assertEquals(canvas, PulseMeterGeometry.barHeight(canvas, 1f, 1f), 0.001f)
    }

    @Test
    fun levelDerivedGeometryNeverReturnsNaN() {
        val weight = PulseMeterGeometry.profileWeight(0)
        assertFalse(PulseMeterGeometry.barHeight(canvas, Float.NaN, weight).isNaN())
        assertFalse(PulseMeterGeometry.barTop(canvas, -5f).isNaN())
    }

    // ---- nextPeak: 收工竞态下的定格峰值契约 ----

    @Test
    fun nextPeakIsAMonotonicMaxUnderTheFinalizeRace() {
        assertEquals(0.6f, PulseMeterGeometry.nextPeak(0f, 0.6f), 0f)
        // finalizeTake 先清零、isBusy 后翻转: 峰值不得被那串 0 偷走。
        assertEquals(0.6f, PulseMeterGeometry.nextPeak(0.6f, 0f), 0f)
        assertEquals(0.9f, PulseMeterGeometry.nextPeak(0.6f, 0.9f), 0f)
    }

    @Test
    fun nextPeakSanitizesGarbage() {
        assertEquals(0.6f, PulseMeterGeometry.nextPeak(0.6f, Float.NaN), 0f)
        assertEquals(0.6f, PulseMeterGeometry.nextPeak(0.6f, -1f), 0f)
        // peak 自身是 NaN: 消毒成 0, 结果由干净的那一路决定。
        assertEquals(0.2f, PulseMeterGeometry.nextPeak(Float.NaN, 0.2f), 0f)
        assertEquals(1f, PulseMeterGeometry.nextPeak(0.6f, 1.7f), 0f)
        assertEquals(0f, PulseMeterGeometry.nextPeak(0f, 0f), 0f)
    }

    // ---- 居中条组几何 ----

    @Test
    fun pulseGroupIsCentredAndStaysInsideCanvas() {
        val barWidth = 10f
        val gap = 14f
        val count = PulseMeterGeometry.BAR_COUNT
        val left = PulseMeterGeometry.barLeft(0, canvas, barWidth, gap)
        val right = PulseMeterGeometry.barLeft(count - 1, canvas, barWidth, gap) + barWidth
        assertEquals("整组水平居中", left, canvas - right, 0.001f)
        assertTrue("最左条不越出画布左缘", left >= 0f)
        assertTrue("最右条不越出画布右缘", right <= canvas)
        // 画布比条组还窄: 贴左缘, 不出现负坐标。
        assertTrue(PulseMeterGeometry.barLeft(0, 30f, barWidth, gap) >= 0f)
        assertEquals(
            count * barWidth + (count - 1) * gap,
            PulseMeterGeometry.groupWidth(count, barWidth, gap),
            0.001f
        )
    }

    // ---- 读屏文案的诚实性 ----

    @Test
    fun contentDescriptionTellsLiveFrozenAndIdleApartHonestly() {
        val loud = 0.7f
        val quiet = 0f
        val live = pulseContentDescription(PulsePresentation.LIVE, loud, loud)
        assertTrue(live.contains("正在录音"))
        assertFalse("脉冲条不滚动, 文案不许再提滚动", live.contains("滚"))
        assertFalse(live.contains("波形"))
        assertTrue(
            pulseContentDescription(PulsePresentation.LIVE, quiet, quiet)
                .contains("还没拾到声音")
        )
        val frozen = pulseContentDescription(PulsePresentation.FROZEN, 0f, 0.6f)
        assertFalse("停录之后不得再播报\"正在录音\"", frozen.contains("正在录音"))
        assertTrue(frozen.contains("峰值"))
        assertTrue(
            pulseContentDescription(PulsePresentation.IDLE, quiet, quiet).contains("空闲")
        )
        // 整条录音全静音的定格要直说, 而不是给一个"峰值 0"的假读数。
        val silentFrozen = pulseContentDescription(PulsePresentation.FROZEN, 0f, 0f)
        assertTrue(silentFrozen.contains("没有拾到声音"))
    }
}
