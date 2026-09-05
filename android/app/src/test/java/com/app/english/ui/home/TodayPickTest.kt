package com.app.english.ui.home

import com.app.english.data.repository.pickTodayScene
import com.app.english.domain.model.SceneSummary
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

/**
 * 「今日推荐」真逻辑(计划 §6.3, P7): 画像最低维 -> 场景 skills 匹配 ->
 * curated 第 1 课兜底。纯 JVM 锁兜底链, 不让推荐位出现空白或假推荐。
 */
class TodayPickTest {
    private fun scene(id: String, skills: List<String>, source: String = "curated") =
        SceneSummary(id = id, source = source, skills = skills)

    private val scenes = listOf(
        scene("scene_ordering_coffee", listOf("pronunciation", "vocabulary", "fluency")),
        scene("scene_workplace_negotiate_deadline", listOf("grammar", "vocabulary", "fluency")),
        scene("scene_travel_airport_checkin", listOf("pronunciation", "fluency"))
    )

    @Test
    fun emptyCatalogRecommendsNothing() {
        assertNull(emptyList<SceneSummary>().pickTodayScene(weakestDimension = "grammar"))
        assertNull(emptyList<SceneSummary>().pickTodayScene(weakestDimension = null))
    }

    @Test
    fun nullWeakestDimensionFallsBackToFirstCurated() {
        // 空画像/stub: 不假装知道你弱在哪, 直接给首门 curated 课。
        assertEquals("scene_ordering_coffee", scenes.pickTodayScene(null)!!.id)
    }

    @Test
    fun weakestDimensionMatchesSceneSkills() {
        assertEquals(
            "scene_workplace_negotiate_deadline",
            scenes.pickTodayScene("grammar")!!.id
        )
        assertEquals("scene_ordering_coffee", scenes.pickTodayScene("pronunciation")!!.id)
    }

    @Test
    fun unmatchedDimensionFallsBackToFirstCurated() {
        // 数据里没有带 "listening" 的场景 -> 退回首门 curated 课。
        assertEquals("scene_ordering_coffee", scenes.pickTodayScene("listening")!!.id)
    }

    @Test
    fun generatedScenesDoNotWinTheColdStartFallback() {
        val onlyGenerated = listOf(
            scene("gen_1", listOf("grammar"), source = "generated")
        )
        assertEquals("没有 curated 时宁可给唯一一门也不空白", "gen_1", onlyGenerated.pickTodayScene(null)!!.id)
    }
}
