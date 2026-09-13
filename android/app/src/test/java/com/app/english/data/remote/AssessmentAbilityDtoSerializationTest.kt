package com.app.english.data.remote

import com.app.english.domain.model.ABILITY_DIMENSIONS
import kotlinx.serialization.json.Json
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 测评/画像/润色载荷的 JSON 反序列化锁(与 NetworkModule 同款 Json 配置)。
 * 样本是照 `backend/app/api/v1/assessment.py` / `ability.py` / `polish.py` 的
 * response_model 手写的真实形状: null 维度、空 radar、stub 判级这些边界必须
 * 在普通 JVM 上就能测到, 不等真机。
 */
class AssessmentAbilityDtoSerializationTest {
    private val json = Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
        encodeDefaults = true
    }

    @Test
    fun assessmentBankDecodesQuestionShape() {
        val bank = json.decodeFromString(
            AssessmentBankDto.serializer(),
            """
            {
              "total": 2,
              "questions": [
                {"id": "q1", "no": 1, "type": "read_aloud", "cefr_anchor": "A2",
                 "cn_prompt": "跟读这句话", "display_text": "Could I have a latte?",
                 "translation_cn": "我要一杯拿铁", "seconds": 30},
                {"id": "q2", "no": 2, "type": "open_question", "cefr_anchor": "B1",
                 "cn_prompt": "聊聊周末计划", "display_text": "",
                 "translation_cn": "", "seconds": 60}
              ]
            }
            """.trimIndent()
        )
        assertEquals(2, bank.total)
        val first = bank.questions.first()
        assertEquals("read_aloud", first.type)
        assertEquals("A2", first.cefrAnchor)
        assertEquals("Could I have a latte?", first.displayText)
        assertEquals(60, bank.questions[1].seconds)
        assertEquals(2, bank.toDomain().questions.size)
    }

    @Test
    fun completeResponseKeepsNullDimsAndStubHonesty() {
        // stub 判级: cefr=null, dims 里有显式 null —— 不能变成 0.0, 不能抛。
        val stub = json.decodeFromString(
            AssessmentCompleteResponseDto.serializer(),
            """
            {
              "attempt_id": "3f2a8f66-9c31-4d2e-8f39-0b2b6d2c1e4a",
              "status": "completed",
              "cefr": null,
              "dims": {"pronunciation": 88.5, "grammar": null, "vocabulary": null, "fluency": null},
              "radar": [
                {"dimension": "pronunciation", "score": 88.5, "max": 100.0, "n": 1},
                {"dimension": "grammar", "score": null, "max": 100.0, "n": 0},
                {"dimension": "vocabulary", "score": null, "max": 100.0, "n": 0},
                {"dimension": "fluency", "score": null, "max": 100.0, "n": 0}
              ],
              "rationale_cn": "LLM 未配置或输出不可用, 本次没有判级。",
              "pronunciation_source": "ise",
              "source": "stub",
              "llm_source": "stub",
              "cefr_level": null
            }
            """.trimIndent()
        ).toDomain()
        assertTrue("source=stub 必须被识别为非判级", stub.isStub)
        assertNull(stub.cefr)
        assertNull(stub.cefrLevel)
        assertEquals(88.5, stub.dims["pronunciation"]!!, 0.0)
        assertNull("null 维度不能变 0.0", stub.dims["grammar"])
        assertEquals(88.5, stub.radarScore("pronunciation")!!, 0.0)
        assertNull(stub.radarScore("fluency"))
    }

    @Test
    fun judgedCompleteResponseCarriesCefrAndRadar() {
        val judged = json.decodeFromString(
            AssessmentCompleteResponseDto.serializer(),
            """
            {
              "attempt_id": "att-1", "status": "completed", "cefr": "B1",
              "dims": {"pronunciation": 74.0, "grammar": 68.5, "vocabulary": 61.0, "fluency": 55.5},
              "radar": [{"dimension": "pronunciation", "score": 74.0, "max": 100.0, "n": 2}],
              "rationale_cn": "能完成日常话题的简单交流。",
              "pronunciation_source": "ise", "source": "llm",
              "llm_source": "qwen3.8-max", "cefr_level": "B1"
            }
            """.trimIndent()
        ).toDomain()
        assertEquals("B1", judged.cefr)
        assertEquals("B1", judged.cefrLevel)
        assertEquals(2, judged.radar.first().n)
    }

    @Test
    fun completeRequestSerializesAsyncJudgeFlag() {
        // 新客户端 opt-in: async_judge=true 必须真的上线(服务端靠它走异步判级)。
        val encoded = json.encodeToString(
            AssessmentCompleteRequestDto.serializer(),
            AssessmentCompleteRequestDto(deviceId = "dev-1", asyncJudge = true)
        )
        assertTrue("async_judge 必须出现在请求体里", encoded.contains("\"async_judge\":true"))
        assertTrue(encoded.contains("\"device_id\":\"dev-1\""))
    }

    @Test
    fun pendingJudgeResponseDecodesToNullJudgement() {
        // 202 判级在途: 只有 attempt_id + status="judging", 其余字段全是默认值 ——
        // toJudgementOrNull 必须返回 null, 不能把"判级中"误当成一份 stub 结果。
        val pending = json.decodeFromString(
            AssessmentCompleteResponseDto.serializer(),
            """{"attempt_id": "att-1", "status": "judging"}"""
        )
        assertNull(pending.toJudgementOrNull())
        assertEquals("att-1", pending.attemptId)
    }

    @Test
    fun legacyTerminalResponseDecodesWithoutPendingFields() {
        // 旧后端(同步判级)的响应没有 judging 形状; 默认值齐全 -> 终态照常映射。
        val legacy = json.decodeFromString(
            AssessmentCompleteResponseDto.serializer(),
            """
            {
              "attempt_id": "att-legacy",
              "cefr": "A2",
              "dims": {"pronunciation": null, "grammar": 55.0, "vocabulary": 48.0, "fluency": 40.0},
              "radar": [],
              "rationale_cn": "能完成 A2 题的简单交流。",
              "source": "llm", "llm_source": "qwen3.8-max", "cefr_level": "A2"
            }
            """.trimIndent()
        )
        assertEquals("att-legacy", legacy.attemptId)
        val judgement = legacy.toJudgementOrNull()
        assertEquals("A2", judgement!!.cefr)
        assertEquals(55.0, judgement.dims["grammar"]!!, 0.0)
    }

    @Test
    fun abilityResponseDecodesEmptyAndRealShapes() {
        // 未知 device: 后端返回全 null 空画像骨架, 不是 404。
        val empty = json.decodeFromString(
            AbilityResponseDto.serializer(),
            """
            {"device_id": "dev-x", "user_found": false,
             "profile": {"pronunciation": null, "grammar": null, "vocabulary": null, "fluency": null},
             "n": {"pronunciation": 0, "grammar": 0, "vocabulary": 0, "fluency": 0},
             "radar": [], "days": 30, "trajectory": [], "real_events": 0}
            """.trimIndent()
        ).toDomain()
        assertNull(empty.cefrLevel)
        assertTrue(empty.userFound.not())
        for (dimension in ABILITY_DIMENSIONS) {
            assertTrue(empty.lacksEvidence(dimension))
        }

        val real = json.decodeFromString(
            AbilityResponseDto.serializer(),
            """
            {"device_id": "dev-1", "user_id": "u-1", "user_found": true,
             "profile": {"pronunciation": 82.0, "grammar": 60.0, "vocabulary": null, "fluency": 71.0},
             "n": {"pronunciation": 6, "grammar": 3, "vocabulary": 0, "fluency": 4},
             "radar": [{"dimension": "grammar", "score": 60.0, "max": 100.0, "n": 3}],
             "cefr_level": "A2", "assessment_cefr": "A2", "band_locked": true,
             "derived_level": "B1", "days": 7,
             "trajectory": [
               {"date": "2026-09-03", "pronunciation": 80.0, "grammar": null,
                "vocabulary": null, "fluency": 66.0, "events": 2},
               {"date": "2026-09-04", "pronunciation": 84.0, "grammar": 62.0,
                "vocabulary": null, "fluency": 72.0, "events": 3}
             ],
             "real_events": 5, "updated_at": "2026-09-04T10:00:00Z"}
            """.trimIndent()
        ).toDomain()
        assertEquals("A2", real.cefrLevel)
        assertTrue(real.bandLocked)
        assertEquals(3, real.sampleCount("grammar"))
        assertEquals("grammar", real.weakestDimension())
        assertEquals(2, real.trajectory.size)
        assertNull("null 轨迹点保持 null", real.trajectory[0].grammar)
        assertEquals(7, real.days)
    }

    @Test
    fun polishResponseHandlesNullPolishAndCollectedId() {
        val noIssue = json.decodeFromString(
            PolishResponseDto.serializer(),
            """{"polish": null, "source": "llm", "llm_source": "qwen3.8-max",
               "expression_id": null, "note_cn": "这句没有值得改的语法/用词问题。"}"""
        ).toDomain()
        assertTrue("polish=null 是诚实的没问题, 不是失败", noIssue.polish == null)
        assertEquals("这句没有值得改的语法/用词问题。", noIssue.noteCn)

        val collected = json.decodeFromString(
            PolishResponseDto.serializer(),
            """{"polish": {"original": "I go to shop yesterday",
                           "polished": "I went to the shop yesterday",
                           "explanation_cn": "一般过去时"},
               "source": "llm", "llm_source": "qwen3.8-max",
               "expression_id": "expr-1", "note_cn": "已收藏进个人表达库。"}"""
        ).toDomain()
        assertTrue(collected.hasPolish)
        assertEquals("expr-1", collected.expressionId)
        assertEquals("I went to the shop yesterday", collected.polish?.polished)
    }
}
