package com.app.english.ui.courses

import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** 情景课画廊的纯筛选/文案逻辑(计划 §6.3「分类筛选 chips」)。 */
class SceneFilterTest {
    private val categories = listOf(
        SceneCategoryStat("daily", "日常交流", 2),
        SceneCategoryStat("workplace", "职场商务", 2),
        SceneCategoryStat("exam", "考试面试", 2),
        SceneCategoryStat("travel", "旅行出国", 2)
    )

    private fun scene(id: String, category: String, level: String = "B1") = SceneSummary(
        id = id,
        category = category,
        title = id,
        level = level,
        estMinutes = 9,
        taskCount = 4
    )

    private val scenes = listOf(
        scene("a", "daily"),
        scene("b", "workplace"),
        scene("c", "workplace", level = "A2")
    )

    @Test
    fun nullBlankAndAllShowEverything() {
        assertEquals(3, SceneFilter.apply(null, scenes).size)
        assertEquals(3, SceneFilter.apply("   ", scenes).size)
        assertEquals(3, SceneFilter.apply(CATEGORY_ALL_ID, scenes).size)
    }

    @Test
    fun unknownCategoryDoesNotEmptyTheList() {
        // 宁多勿少: 筛选值由后端解释, 客户端不把拼错的分类渲染成「暂无课程」。
        assertEquals(3, SceneFilter.apply("no-such-category", scenes).size)
    }

    @Test
    fun categoryFilterIsCaseAndSpaceInsensitive() {
        val picked = SceneFilter.apply("  WORKPLACE ", scenes)
        assertEquals(listOf("b", "c"), picked.map { it.id })
        assertTrue(SceneFilter.apply("daily", scenes).single().id == "a")
    }

    @Test
    fun chipsPrependAllWithTotalCount() {
        val chips = SceneFilter.chips(categories)
        assertEquals(5, chips.size)
        assertEquals(CATEGORY_ALL_ID, chips.first().id)
        assertEquals("全部", chips.first().label)
        assertEquals(8, chips.first().count)
        assertTrue(chips.first().isAll)
        assertEquals(
            listOf("daily", "workplace", "exam", "travel"),
            chips.drop(1).map { it.id }
        )
        assertEquals(listOf(2, 2, 2, 2), chips.drop(1).map { it.count })
    }

    @Test
    fun chipsFallBackToFourCanonicalCategories() {
        val chips = SceneFilter.chips(emptyList())
        assertEquals(
            listOf(CATEGORY_ALL_ID, "daily", "workplace", "exam", "travel"),
            chips.map { it.id }
        )
        assertEquals(listOf("日常交流", "职场商务", "考试面试", "旅行出国"), chips.drop(1).map { it.label })
        assertTrue(chips.drop(1).all { it.count == 0 })
    }

    @Test
    fun chipsDeduplicateAndKeepUnknownIds() {
        val chips = SceneFilter.chips(
            listOf(
                SceneCategoryStat("daily", "日常交流", 3),
                SceneCategoryStat("daily", "重复的", 9),
                SceneCategoryStat("", "空的", 5),
                SceneCategoryStat("shop", "", 1)
            )
        )
        assertEquals(listOf(CATEGORY_ALL_ID, "daily", "shop"), chips.map { it.id })
        assertEquals(4, chips.first().count)
        assertEquals("日常交流", chips[1].label)
        // 后端没给中文时用兜底名, 未知分类没有兜底就原样显示 id
        assertEquals("shop", chips[2].label)
    }

    @Test
    fun backendLabelWinsOverFallback() {
        assertEquals("日常交流", SceneFilter.labelFor("daily", "日常交流"))
        assertEquals("职场商务", SceneFilter.labelFor("workplace", "  "))
        assertEquals("考试面试", SceneFilter.labelFor("exam"))
        assertEquals("other", SceneFilter.labelFor("other"))
    }

    @Test
    fun summaryLineJoinsOnlyWhatExists() {
        assertEquals("B1 · 约 9 分钟 · 4 个任务", SceneFilter.summaryLine(scenes[0]))
        assertEquals("", SceneFilter.summaryLine(SceneSummary(id = "x")))
        assertEquals("A2", SceneFilter.summaryLine(SceneSummary(id = "x", level = "A2")))
        assertEquals(
            "约 8 分钟 · 3 个任务",
            SceneFilter.summaryLine(SceneSummary(id = "x", estMinutes = 8, taskCount = 3))
        )
    }

    @Test
    fun skillPreviewIsCappedAndTrimmed() {
        val withSkills = scene("d", "daily").copy(skills = listOf("点单", " ", "闲聊", "电话", "付款"))
        assertEquals("点单 · 闲聊 · 电话", SceneFilter.skillPreview(withSkills))
        assertEquals("", SceneFilter.skillPreview(scene("e", "daily")))
    }

    @Test
    fun segmentsKeepPlanOrderAndLabels() {
        assertEquals(listOf("情景课", "课本"), CourseSegment.entries.map { it.label })
        assertEquals(CourseSegment.SCENES, CourseSegment.entries.first())
    }
}
