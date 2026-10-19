package com.app.english.data.remote

import kotlinx.serialization.builtins.ListSerializer
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
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
    fun scoreResponse_decodesSnakeCaseFields() {
        val payload = """
            {"total":87.0,"pronunciation":90.0,"fluency":85.0,"completeness":88.0,
             "word_details":[{"word":"hello","score":92.0,"ipa":"həˈloʊ"}],
             "suggestion":"注意 th 的咬舌音"}
        """.trimIndent()
        val dto = json.decodeFromString(ScoreResponseDto.serializer(), payload)
        assertEquals(87.0, dto.total, 0.0)
        assertEquals(90.0, dto.pronunciation, 0.0)
        assertEquals(85.0, dto.fluency, 0.0)
        assertEquals(88.0, dto.completeness, 0.0)
        assertEquals(1, dto.wordDetails.size)
        assertEquals("hello", dto.wordDetails[0].word)
        assertEquals(92.0, dto.wordDetails[0].score, 0.0)
        assertEquals("həˈloʊ", dto.wordDetails[0].ipa)
        assertEquals("注意 th 的咬舌音", dto.suggestion)
    }

    @Test
    fun scoreResponse_missingSuggestion_decodesToNull() {
        val payload = """
            {"total":50.0,"pronunciation":50.0,"fluency":50.0,"completeness":50.0,"word_details":[]}
        """.trimIndent()
        val dto = json.decodeFromString(ScoreResponseDto.serializer(), payload)
        assertNull(dto.suggestion)
        assertTrue(dto.wordDetails.isEmpty())
    }

    @Test
    fun lessonDetail_decodesRolesAndLines() {
        val payload = """
            {"id":1,"book":"nce1","lesson_no":1,"title":"A Private Conversation",
             "roles":[{"name":"A","lines":[
                {"id":"L1-001-A","text":"Excuse me","translation":"打扰一下","ipa":null}
             ]}]}
        """.trimIndent()
        val dto = json.decodeFromString(LessonDetailDto.serializer(), payload)
        assertEquals(1, dto.lessonNo)
        assertEquals("A Private Conversation", dto.title)
        assertEquals(1, dto.roles.size)
        assertEquals("A", dto.roles[0].name)
        assertEquals("L1-001-A", dto.roles[0].lines[0].id)
        assertEquals("Excuse me", dto.roles[0].lines[0].text)
        assertEquals("打扰一下", dto.roles[0].lines[0].translation)
        assertNull(dto.roles[0].lines[0].ipa)
    }

    @Test
    fun scoreRequest_serializesAudioAsStringWithSnakeCase() {
        val request = ScoreRequestDto(
            lessonId = 1,
            lineId = "L1-001-A",
            refText = "hi",
            mode = "k12",
            audio = "BASE64DATA"
        )
        val encoded = json.encodeToString(ScoreRequestDto.serializer(), request)
        assertTrue(encoded.contains("\"audio\":\"BASE64DATA\""))
        assertTrue(encoded.contains("\"lesson_id\":1"))
        assertTrue(encoded.contains("\"line_id\":\"L1-001-A\""))
        assertTrue(encoded.contains("\"ref_text\":\"hi\""))
        assertTrue(encoded.contains("\"mode\":\"k12\""))
        assertFalse(encoded.contains("audio_url"))
    }

    @Test
    fun historyItem_decodesSnakeCaseFields() {
        val payload = """
            {"id":"abc","lesson_id":1,"line_id":"L1","score_total":80.0,
             "score_pronunciation":80.0,"score_fluency":80.0,"score_completeness":80.0,
             "created_at":"2026-07-12T10:00:00"}
        """.trimIndent()
        val dto = json.decodeFromString(HistoryItemDto.serializer(), payload)
        assertEquals("abc", dto.id)
        assertEquals(1, dto.lessonId)
        assertEquals("L1", dto.lineId)
        assertEquals(80.0, dto.scoreTotal, 0.0)
        assertEquals(80.0, dto.scorePronunciation, 0.0)
        assertEquals("2026-07-12T10:00:00", dto.createdAt)
    }

    @Test
    fun historyItem_decodesKindAndLabel_withBackwardDefaults() {
        // P8·2f: 服务端 add-only 新字段; 旧 payload 必须落在安全默认值上。
        val modern = """
            {"id":"h2","book":"scenes","lesson_id":0,"line_id":"s1-a",
             "kind":"scene_course","label":"点一杯拿铁 · 实战对话",
             "score_total":80.0,"score_pronunciation":80.0,"score_fluency":80.0,
             "score_completeness":80.0,"created_at":"2026-07-12T10:00:00"}
        """.trimIndent()
        val dto = json.decodeFromString(HistoryItemDto.serializer(), modern)
        assertEquals("scene_course", dto.kind)
        assertEquals("点一杯拿铁 · 实战对话", dto.label)
        val domain = dto.toDomain()
        assertEquals("scene_course", domain.kind)
        assertEquals("点一杯拿铁 · 实战对话", domain.label)

        val legacy = """
            {"id":"h1","lesson_id":1,"line_id":"L1","score_total":80.0,
             "score_pronunciation":80.0,"score_fluency":80.0,"score_completeness":80.0,
             "created_at":"2026-07-12T10:00:00"}
        """.trimIndent()
        val legacyItem = json.decodeFromString(HistoryItemDto.serializer(), legacy).toDomain()
        assertEquals("lesson", legacyItem.kind)
        assertEquals("", legacyItem.label)
    }

    @Test
    fun historyWriteRequest_serializesAllFields() {
        val request = HistoryWriteRequestDto(
            deviceId = "dev-1",
            lessonId = 2,
            lineId = "L2",
            audioPath = "/tmp/a.m4a",
            scoreTotal = 70.0,
            scorePronunciation = 70.0,
            scoreFluency = 70.0,
            scoreCompleteness = 70.0
        )
        val encoded = json.encodeToString(HistoryWriteRequestDto.serializer(), request)
        assertTrue(encoded.contains("\"device_id\":\"dev-1\""))
        assertTrue(encoded.contains("\"lesson_id\":2"))
        assertTrue(encoded.contains("\"audio_path\":\"/tmp/a.m4a\""))
        assertTrue(encoded.contains("\"score_total\":70.0"))
    }

    @Test
    fun ttsResponse_decodes() {
        val payload = """{"audio_url":"http://host/a.mp3","duration_ms":1234}"""
        val dto = json.decodeFromString(TtsResponseDto.serializer(), payload)
        assertEquals("http://host/a.mp3", dto.audioUrl)
        assertEquals(1234, dto.durationMs)
    }

    @Test
    fun lessonSummaryList_decodes() {
        val payload = """
            [{"id":1,"book":"nce1","lesson_no":1,"title":"A","role_count":2,"duration_s":0.0},
             {"id":2,"book":"nce1","lesson_no":2,"title":"B","role_count":3,"duration_s":0.0}]
        """.trimIndent()
        val list = json.decodeFromString(
            ListSerializer(LessonSummaryDto.serializer()),
            payload
        )
        assertEquals(2, list.size)
        assertEquals(1, list[0].lessonNo)
        assertEquals(2, list[0].roleCount)
        assertEquals("B", list[1].title)
    }

    @Test
    fun dialogueGenerateResponse_decodesSuggestedReply() {
        val payload = """
            {"scene_id":"daily_conversation","status":"stub","title":"Daily conversation",
             "lines":[{"id":"line-1","role":"assistant","text":"Hi!","is_user":false}],
             "suggested_reply":"I am fine."}
        """.trimIndent()
        val dto = json.decodeFromString(DialogueGenerateResponseDto.serializer(), payload)
        assertEquals("daily_conversation", dto.sceneId)
        assertEquals("Hi!", dto.lines.first().text)
        assertEquals("I am fine.", dto.suggestedReply)
    }

    @Test
    fun dialogueTurnRequest_serializesSnakeCaseFields() {
        val request = DialogueTurnRequestDto(
            sceneId = "daily_conversation",
            history = listOf(DialogueMessageDto("assistant", "Hi!")),
            userAudioB64 = "AAAA"
        )
        val encoded = json.encodeToString(DialogueTurnRequestDto.serializer(), request)
        assertTrue(encoded.contains("\"scene_id\":\"daily_conversation\""))
        assertTrue(encoded.contains("\"user_audio_b64\":\"AAAA\""))
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
    fun dialogueGenerateRequest_serializesModelId() {
        val request = DialogueGenerateRequestDto(
            scene = "daily_conversation",
            mode = "adult",
            modelId = "qwen-plus"
        )
        val encoded = json.encodeToString(DialogueGenerateRequestDto.serializer(), request)
        assertTrue(
            "missing model_id field: $encoded",
            encoded.contains("\"model_id\":\"qwen-plus\"")
        )
    }

    @Test
    fun dialogueTurnRequest_serializesModelId() {
        val request = DialogueTurnRequestDto(
            sceneId = "daily_conversation",
            history = listOf(DialogueMessageDto("assistant", "Hi!")),
            modelId = "qwen-turbo"
        )
        val encoded = json.encodeToString(DialogueTurnRequestDto.serializer(), request)
        assertTrue(
            "missing model_id field: $encoded",
            encoded.contains("\"model_id\":\"qwen-turbo\"")
        )
    }

    @Test
    fun booksResponse_decodesCatalog() {
        val payload = """
            {
              "books":[
                {"id":"nce1","display_name":"新概念英语 第一册","description":"入门","level":"beginner","lesson_count":1},
                {"id":"nce2","display_name":"新概念英语 第二册","description":"进阶","level":"intermediate","lesson_count":2}
              ],
              "default_book":"nce1"
            }
        """.trimIndent()
        val dto = json.decodeFromString(BooksResponseDto.serializer(), payload)
        assertEquals(2, dto.books.size)
        assertEquals("新概念英语 第一册", dto.books[0].displayName)
        assertEquals("nce1", dto.defaultBook)
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
    fun statsResponse_decodesAggregates() {
        val payload = """
            {
              "total_sessions":12,
              "avg_total":82.5,
              "avg_pronunciation":85.0,
              "avg_fluency":80.0,
              "avg_completeness":83.0,
              "best_total":95.0,
              "recent_sessions":5,
              "streak_days":3,
              "daily":[
                {"date":"2026-07-15","avg_total":75.0,"avg_pronunciation":78.0,"avg_fluency":72.0,"avg_completeness":77.0,"sessions":2}
              ],
              "lessons_attempted":[1,2,3]
            }
        """.trimIndent()
        val dto = json.decodeFromString(StatsResponseDto.serializer(), payload)
        assertEquals(12, dto.totalSessions)
        assertEquals(82.5, dto.avgTotal, 0.0)
        assertEquals(3, dto.streakDays)
        assertEquals(1, dto.daily.size)
        assertEquals(listOf(1, 2, 3), dto.lessonsAttempted)
    }

    // ---- §A4/D4 双语 add-only: 新键默认值 + 带新值的样本 + 旧样本仍可 decode ----

    /**
     * 台词/示范句/学员那句的中文是**恒键**, 旧后端(或未配 LLM 时的空值)也必须有默认值:
     * 缺键 -> 空串 -> 界面整行不渲染 (D5)。绝不因为缺这三个键让整个响应解码失败 ——
     * 那会把"没有中文"放大成"这一轮对话消失"。
     */
    @Test
    fun dialogueTurnResponse_bilingualKeysDefaultAndDecode() {
        val legacy = """
            {"status":"ready","reply_text":"That sounds fun!","suggested_reply":"I usually hike.",
             "recognized_text":"I went hiking."}
        """.trimIndent()
        val old = json.decodeFromString(DialogueTurnResponseDto.serializer(), legacy)
        assertEquals("", old.replyCn)
        assertEquals("", old.suggestionCn)
        assertEquals("", old.learnerCn)
        assertEquals("That sounds fun!", old.replyText)

        val bilingual = """
            {"status":"ready","reply_text":"That sounds fun!","reply_audio_url":null,
             "suggested_reply":"I usually hike on weekends.",
             "recognized_text":"I went hiking.","model_id":"qwen3.8-flash",
             "polish":null,"grammar_score":null,"vocabulary_score":null,
             "ability_events":[],"llm_source":"qwen3.8-flash",
             "reply_cn":"听起来不错！","suggestion_cn":"我周末一般去徒步。",
             "learner_cn":"我去徒步了。"}
        """.trimIndent()
        val dto = json.decodeFromString(DialogueTurnResponseDto.serializer(), bilingual)
        assertEquals("听起来不错！", dto.replyCn)
        assertEquals("我周末一般去徒步。", dto.suggestionCn)
        assertEquals("我去徒步了。", dto.learnerCn)
        val domain = dto.toDomain()
        assertEquals("听起来不错！", domain.replyCn)
        assertEquals("我周末一般去徒步。", domain.suggestionCn)
        assertEquals("我去徒步了。", domain.learnerCn)
        assertNull(dto.replyAudioUrl)
        // §A3: 这一条响应里的 `polish`/`grammar_score`/`vocabulary_score` 恒为 null (判分
        // 移出了这条请求)。客户端 DTO **刻意不建**这三个字段 —— 它们从来没有任何消费点
        // (自由对话的润色走 `POST /polish`), add-only 加进来就是死代码。上面那份样本带着
        // 这三个键仍然解得出来, 本身就是「旧客户端忽略未知键」那条纪律的现场证明。
        assertEquals("That sounds fun!", dto.replyText)
    }

    /** §A4/A5: 已展示参考句 + 身份随请求回去 (服务端靠它防复写 / 记画像)。 */
    @Test
    fun dialogueTurnRequest_serializesShownSuggestionsAndIdentity() {
        val request = DialogueTurnRequestDto(
            sceneId = "custom_3f1c",
            history = listOf(DialogueMessageDto("assistant", "Hi!")),
            userAudioB64 = "AAAA",
            modelId = "qwen-plus",
            deviceId = "dev-1",
            shownSuggestions = listOf("I'd like a latte.", "To go, please.")
        )
        val encoded = json.encodeToString(DialogueTurnRequestDto.serializer(), request)
        assertTrue(encoded.contains("\"device_id\":\"dev-1\""))
        assertTrue(
            encoded.contains("\"shown_suggestions\":[\"I'd like a latte.\",\"To go, please.\"]")
        )
        // 不带已展示清单时是空数组而不是省略: 服务端两种读法等价, 但显式空更诚实。
        val bare = json.encodeToString(
            DialogueTurnRequestDto.serializer(),
            DialogueTurnRequestDto(sceneId = "daily_conversation", history = emptyList())
        )
        assertTrue(bare.contains("\"shown_suggestions\":[]"))
    }

    /**
     * 场景目录的英文对照 (§3 C3b 最终形状): **catalog 行恒非空, custom 行恒为空串**
     * (自定义场景按学员自己描述的语言展示 —— 那两格是设计性空, 不是缺数据)。
     * 旧样本(完全没有这两个键)仍要能 decode。
     */
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
