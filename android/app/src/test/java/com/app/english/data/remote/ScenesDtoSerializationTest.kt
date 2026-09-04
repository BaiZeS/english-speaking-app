package com.app.english.data.remote

import com.app.english.data.repository.RECOMMENDED_SCENE_ID
import com.app.english.data.repository.pickRecommended
import com.app.english.domain.model.SceneSummary
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * `GET /scenes` 的线上契约固件测试(后端 `scene_store.ScenesPage` / `SceneSummary`)。
 *
 * Json 配置刻意与 `NetworkModule.provideJson()` 保持一致 —— 解码韧性必须以真正
 * 跑在线上的那套配置为准。
 */
class ScenesDtoSerializationTest {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
        encodeDefaults = true
    }

    private val fullPage = """
        {
          "categories": [
            {"id":"daily","label_cn":"日常交流","count":2},
            {"id":"workplace","label_cn":"职场商务","count":2},
            {"id":"exam","label_cn":"考试面试","count":2},
            {"id":"travel","label_cn":"旅行出国","count":2}
          ],
          "scenes": [
            {
              "id":"scene_workplace_project_update",
              "source":"curated",
              "category":"workplace",
              "title":"项目进展汇报",
              "subtitle_en":"Reporting project progress",
              "level":"B1",
              "est_minutes":9,
              "brief_cn":"用英文把进度、风险和下一步讲清楚。",
              "skills":["汇报","提问","约定"],
              "vocab_count":8,
              "briefing_count":5,
              "task_count":4,
              "required_task_count":3,
              "max_turns":12,
              "cleared":false,
              "best_total":0.0,
              "attempts":0
            },
            {
              "id":"scene_ordering_coffee",
              "source":"curated",
              "category":"daily",
              "title":"咖啡店点单",
              "subtitle_en":"Ordering at a coffee shop",
              "level":"A2",
              "est_minutes":8,
              "brief_cn":"点一杯想要的咖啡。",
              "skills":["点单"],
              "vocab_count":6,
              "briefing_count":4,
              "task_count":3,
              "required_task_count":2,
              "max_turns":10,
              "cleared":true,
              "best_total":88.5,
              "attempts":2
            }
          ],
          "total":2,
          "some_future_field":{"ignored":true}
        }
    """.trimIndent()

    @Test
    fun decodesBackendContractVerbatim() {
        val dto = json.decodeFromString(ScenesResponseDto.serializer(), fullPage)
        assertEquals(4, dto.categories.size)
        assertEquals("日常交流", dto.categories[0].labelCn)
        assertEquals(2, dto.categories[0].count)
        assertEquals("travel", dto.categories[3].id)
        assertEquals(2, dto.scenes.size)
        assertEquals(2, dto.total)
        val first = dto.scenes[0]
        assertEquals("scene_workplace_project_update", first.id)
        assertEquals("curated", first.source)
        assertEquals("workplace", first.category)
        assertEquals("Reporting project progress", first.subtitleEn)
        assertEquals("B1", first.level)
        assertEquals(9, first.estMinutes)
        assertEquals("用英文把进度、风险和下一步讲清楚。", first.briefCn)
        assertEquals(listOf("汇报", "提问", "约定"), first.skills)
        assertEquals(8, first.vocabCount)
        assertEquals(5, first.briefingCount)
        assertEquals(4, first.taskCount)
        assertEquals(3, first.requiredTaskCount)
        assertEquals(12, first.maxTurns)
        assertEquals(88.5, dto.scenes[1].bestTotal, 0.0)
        assertEquals(2, dto.scenes[1].attempts)
    }

    @Test
    fun mapsToDomainWithoutLosingFields() {
        val catalog = json.decodeFromString(ScenesResponseDto.serializer(), fullPage).toDomain()
        assertEquals(4, catalog.categories.size)
        assertEquals("职场商务", catalog.categories[1].labelCn)
        assertEquals("scene_ordering_coffee", catalog.scenes[1].id)
        assertTrue(catalog.scenes[1].cleared)
        assertTrue(catalog.scenes[1].isPracticed)
        assertFalse(catalog.scenes[0].isPracticed)
        assertEquals(2, catalog.total)
        assertNull(catalog.defaultSceneId)
    }

    @Test
    fun onlyIdIsEnough_defaultsStayFalseSafe() {
        val payload = """{"categories":[],"scenes":[{"id":"scene_minimal"}],"total":1}"""
        val dto = json.decodeFromString(ScenesResponseDto.serializer(), payload)
        val scene = dto.scenes.single()
        assertEquals("scene_minimal", scene.id)
        assertEquals("curated", scene.source)
        assertEquals("", scene.category)
        assertEquals("", scene.title)
        assertEquals(0, scene.estMinutes)
        assertTrue(scene.skills.isEmpty())
        // 通关进度在 P4 之前恒为默认值, UI 必须按 false/0 渲染
        assertFalse(scene.cleared)
        assertEquals(0.0, scene.bestTotal, 0.0)
        assertEquals(0, scene.attempts)
        assertTrue(dto.categories.isEmpty())
    }

    @Test
    fun nullOptionalStringsCoerceToDefaults() {
        val payload = """
            {"categories":[],"total":0,"scenes":[
              {"id":"x","subtitle_en":null,"brief_cn":null,"level":null,"skills":null}
            ]}
        """.trimIndent()
        val dto = json.decodeFromString(ScenesResponseDto.serializer(), payload)
        val scene = dto.scenes.single()
        assertEquals("", scene.subtitleEn)
        assertEquals("", scene.briefCn)
        assertEquals("", scene.level)
        assertTrue(scene.skills.isEmpty())
    }

    @Test
    fun defaultSceneKeyIsOptionalForNow() {
        val payload = """{"categories":[],"scenes":[],"total":0,"default_scene":"scene_a"}"""
        val dto = json.decodeFromString(ScenesResponseDto.serializer(), payload)
        assertEquals("scene_a", dto.defaultScene)
        assertEquals("scene_a", dto.toDomain().defaultSceneId)
    }

    @Test
    fun recommendedPickTargetsTheCuratedStarterCourse() {
        val catalog = json.decodeFromString(ScenesResponseDto.serializer(), fullPage).toDomain()
        // 「今日推荐」冷启动固定给这节 curated 职场课(计划 §6.3), 与后端内容清单对齐。
        assertEquals("scene_workplace_project_update", RECOMMENDED_SCENE_ID)
        assertEquals(RECOMMENDED_SCENE_ID, catalog.scenes.pickRecommended()?.id)
        // 后端换了内容清单 -> 退回首门课, 不给空白卡
        val withoutStarter = catalog.scenes.drop(1)
        assertEquals(
            "scene_ordering_coffee",
            withoutStarter.pickRecommended("scene_not_present")?.id
        )
        assertNull(emptyList<SceneSummary>().pickRecommended())
    }
}
