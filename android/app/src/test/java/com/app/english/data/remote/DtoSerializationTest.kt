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
}
