package com.app.english.ui.theme

import androidx.compose.ui.graphics.Color
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 暖栗色系的主题 token 契约测试(计划 §6.2 的表格 = 代码里的常量)。
 *
 * 「对标可栗」是这一版的硬性要求, 所以把 §6.2 点名的 8 个 token 在亮/暗两套里的
 * 精确取值钉死: 谁改了色值但没同步改设计结论, 这条测试先红。
 *
 * 断言写成 `Color(hex) == token`(而不是比 `Color.value` 的位排布), 这样测试锁定的是
 * 「这个 token 必须由这枚十六进制字面量构成」, 与 Compose 内部的打包字节序无关。
 */
class ChestnutPaletteTest {
    private fun assertToken(name: String, expectedHex: Long, actual: Color) {
        assertTrue(
            "$name 必须等于计划 §6.2 的取值(要改请先同步设计文档)",
            Color(expectedHex) == actual
        )
    }

    @Test
    fun lightSchemeMatchesTheTokenTable() {
        assertToken("light primary", 0xFFB4552D, Primary)
        assertToken("light onPrimary", 0xFFFFFFFF, OnPrimary)
        assertToken("light secondary", 0xFF8D6E63, Secondary)
        assertToken("light tertiary", 0xFFFFB74D, Tertiary)
        assertToken("light background", 0xFFFFF8F2, Background)
        assertToken("light surface", 0xFFFFFFFF, Surface)
        assertToken("light surfaceVariant", 0xFFF5E9DF, SurfaceVariant)
        assertToken("light error", 0xFFBA1A1A, ErrorLight)
    }

    @Test
    fun darkSchemeMatchesTheTokenTable() {
        assertToken("dark primary", 0xFFE8B48F, PrimaryDark)
        assertToken("dark onPrimary", 0xFF3E1F0E, OnPrimaryDark)
        assertToken("dark secondary", 0xFFD7C1B5, SecondaryDark)
        assertToken("dark tertiary", 0xFFFFCC80, TertiaryDark)
        assertToken("dark background", 0xFF1C1613, BackgroundDark)
        assertToken("dark surface", 0xFF28211C, SurfaceDark)
        assertToken("dark surfaceVariant", 0xFF3A2F28, SurfaceVariantDark)
        assertToken("dark error", 0xFFFFB4AB, ErrorDark)
    }

    @Test
    fun sceneCategoryAccentsAreDistinct() {
        // 画廊 2 列分类卡靠色相区分, 不能有两张同色
        val accents = listOf(SceneDailyColor, SceneWorkplaceColor, SceneExamColor, SceneTravelColor)
        assertTrue("分类卡底色必须互不相同", accents.toSet().size == accents.size)
    }

    @Test
    fun scoreBandColorsStaySemantic() {
        // 计划 §6.2: 三档分数语义色不随品牌换色
        assertTrue(Color(0xFF2E7D32) == ScoreGreen)
        assertTrue(Color(0xFFF9A825) == ScoreYellow)
        assertTrue(Color(0xFFC62828) == ScoreRed)
    }
}
