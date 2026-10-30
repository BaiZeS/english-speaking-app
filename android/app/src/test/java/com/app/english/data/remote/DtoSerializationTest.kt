package com.app.english.data.remote

import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DtoSerializationTest {
    private val json = Json {
        ignoreUnknownKeys = true
        explicitNulls = false
        coerceInputValues = true
        encodeDefaults = true
    }

    @Test
    fun ttsResponse_decodes() {
        val payload = """{"audio_url":"http://host/a.mp3","duration_ms":1234}"""
        val dto = json.decodeFromString(TtsResponseDto.serializer(), payload)
        assertEquals("http://host/a.mp3", dto.audioUrl)
        assertEquals(1234, dto.durationMs)
    }

    @Test
    fun llmModelsResponse_decodesCatalogAndDefault() {
        val payload = """
            {"models":[
              {"id":"qwen-plus","display_name":"Qwen Plus","provider":"bailian","description":"balance"},
              {"id":"deepseek-v3","display_name":"DeepSeek V3","provider":"bailian","description":"natural"}
             ],"default_model":"qwen-plus"}
        """.trimIndent()
        val dto = json.decodeFromString(LlmModelsResponseDto.serializer(), payload)
        assertEquals(2, dto.models.size)
        assertEquals("qwen-plus", dto.defaultModel)
        assertEquals("Qwen Plus", dto.models[0].displayName)
        assertEquals("bailian", dto.models[0].provider)
    }

    @Test
    fun appVersionResponse_decodesAllFields() {
        val payload = """
            {"latest_version":"1.2.0","min_supported_version":"1.0.0",
             "apk_url":"https://example.com/app.apk",
             "release_notes":"new",
             "force_update":true}
        """.trimIndent()
        val dto = json.decodeFromString(AppVersionResponseDto.serializer(), payload)
        assertEquals("1.2.0", dto.latestVersion)
        assertEquals("1.0.0", dto.minSupportedVersion)
        assertEquals("https://example.com/app.apk", dto.apkUrl)
        assertTrue(dto.forceUpdate)
    }

    @Test
    fun dialogueScenesResponse_decodesCatalog() {
        val payload = """
            {
              "scenes":[
                {"id":"daily_conversation","title":"日常寒暄","description":"聊聊今天"},
                {"id":"ordering_coffee","title":"点咖啡","description":"咖啡店"}
              ],
              "default_scene":"daily_conversation"
            }
        """.trimIndent()
        val dto = json.decodeFromString(DialogueScenesResponseDto.serializer(), payload)
        assertEquals(2, dto.scenes.size)
        assertEquals("日常寒暄", dto.scenes[0].title)
        assertEquals("daily_conversation", dto.defaultScene)
    }

    @Test
    fun dialogueScenesResponse_englishKeysAndKind() {
        val payload = """
            {
              "scenes":[
                {"id":"ordering_coffee","title":"点咖啡","description":"在咖啡店点单",
                 "title_en":"Ordering Coffee","description_en":"Order drinks at a coffee shop.",
                 "kind":"catalog"},
                {"id":"custom_9c2b","title":"和外教聊我的周末","description":"聊周末做了什么",
                 "title_en":"","description_en":"","kind":"custom"}
              ],
              "default_scene":"ordering_coffee"
            }
        """.trimIndent()
        val dto = json.decodeFromString(DialogueScenesResponseDto.serializer(), payload)
        val catalog = dto.scenes[0].toDomain()
        assertEquals("Ordering Coffee", catalog.titleEn)
        assertEquals("Order drinks at a coffee shop.", catalog.descriptionEn)
        assertEquals("catalog", catalog.kind)
        assertFalse(catalog.isCustom)

        val custom = dto.scenes[1].toDomain()
        // 两键**存在但为空**: 界面给 custom 行只画中文, 不给空串补第二行 (D5)。
        assertEquals("", custom.titleEn)
        assertEquals("", custom.descriptionEn)
        assertEquals("custom", custom.kind)
        assertTrue(custom.isCustom)
        // 43 字符级的 id 原样透传, 客户端不截断也不假设它是短串。
        assertEquals("custom_9c2b", custom.id)

        val legacy = """
            {"scenes":[{"id":"daily_conversation","title":"日常寒暄","description":"聊聊今天"}],
             "default_scene":"daily_conversation"}
        """.trimIndent()
        val old = json.decodeFromString(DialogueScenesResponseDto.serializer(), legacy)
            .scenes[0].toDomain()
        assertEquals("", old.titleEn)
        assertEquals("", old.descriptionEn)
        assertEquals("catalog", old.kind)

        // 判据是"非内置"而不是"等于 custom" (审查 M11): 后端将来多出第三种 kind 时, 默认
        // 落在**不给英文**那一侧, 而不是悄悄开始展示它带来的英文串。
        assertEquals("catalog", com.app.english.domain.model.DialogueScene.KIND_CATALOG)
        assertTrue(
            com.app.english.domain.model.DialogueScene(
                id = "future_kind",
                title = "标题",
                description = "描述",
                titleEn = "Should not be shown",
                kind = "something_else"
            ).isCustom
        )
    }

    /** §3 C3: 描述自定义场景的入参键名 (scene_brief + 身份)。 */
    @Test
    fun customSceneRequest_serializesBriefAndIdentity() {
        val request = CustomSceneRequestDto(
            sceneBrief = "和外教聊我的周末",
            deviceId = "dev-1"
        )
        val encoded = json.encodeToString(CustomSceneRequestDto.serializer(), request)
        assertTrue(encoded.contains("\"scene_brief\":\"和外教聊我的周末\""))
        assertTrue(encoded.contains("\"device_id\":\"dev-1\""))
    }

    /** §3 C3: 生成任务轮询载荷多了 `kind` —— 自定义场景作业与整课作业同居一张表。 */
    @Test
    fun generationJob_decodesKindWithCourseDefault() {
        val sceneBrief = json.decodeFromString<GenerationJobDto>(
            """{"job_id":"j1","status":"ready","progress":1.0,"stage_text":"生成完成",
                "scene_id":"custom_9c2b","error":null,"kind":"scene_brief"}"""
        )
        assertEquals("scene_brief", sceneBrief.kind)
        assertEquals("custom_9c2b", sceneBrief.sceneId)
        // 旧后端没有这个键 -> `course` (整课生成是唯一的老用途)。
        val legacy = json.decodeFromString<GenerationJobDto>(
            """{"job_id":"j2","status":"running","progress":0.1,"stage_text":"理解学习目标…"}"""
        )
        assertEquals("course", legacy.kind)
    }
}
