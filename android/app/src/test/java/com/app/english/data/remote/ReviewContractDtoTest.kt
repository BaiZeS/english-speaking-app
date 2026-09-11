package com.app.english.data.remote

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * §P6 异步收工契约的 DTO/映射往返锁。
 *
 * 与 `SessionDtoRealSampleTest`(2026-09-05 本机抓的真实样本, 形状属于 §P6 之前)分开,
 * 因为这里的载荷是照**当前** pydantic 模型手工写的: 收工改 202 之后, 那几个新键
 * (`review_status` / `evidence_note_cn`)还没有真机样本可锁。
 */
class ReviewContractDtoTest {
    private val json = kotlinx.serialization.json.Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
        encodeDefaults = true
    }

    /**
     * §P6 契约变更(**不是**回归): `POST /sessions/{id}/finish-mission` 改回 **202**, 载荷里
     * 没有 `report` 了 —— 那一次请求只为等 AI 文案就烧掉 68s(最坏 125s), 而手机 OkHttp
     * `readTimeout` 是 30s, 结果"报告已落库、学员看不见"。样本按 `FinishMissionResponse`
     * 的当前形状写: 五个键, 一个不多。
     */
    @Test
    fun finishMissionReturnsAcceptedWithoutReport() {
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95","revision":11,
             "stage":"review","status":"completed","review_status":"generating"}
        """.trimIndent()
        val ack = json.decodeFromString<FinishMissionResponseDto>(payload).toFinishAck()
        assertEquals("7dacd6e9-1653-4c42-82f1-e3aea298aa95", ack.sessionId)
        assertEquals(11, ack.revision)
        assertEquals("generating", ack.reviewStatus)
    }

    /**
     * 旧载荷(还带 `report`)必须照解不误: `ignoreUnknownKeys` 是唯一挡住"后端多回一个键就把
     * 收工打成解码异常"的东西 —— 灰度期飞在队列里的旧响应正是那个形状。
     */
    @Test
    fun acceptedPayloadToleratesTheRetiredReportField() {
        val payload = """
            {"session_id":"s1","revision":3,"stage":"review","status":"completed",
             "review_status":"generating",
             "report":{"session_id":"s1","scene_id":"scene_ordering_coffee","overall":80.2}}
        """.trimIndent()
        assertEquals(
            "generating",
            json.decodeFromString<FinishMissionResponseDto>(payload).reviewStatus
        )
    }

    /** 状态键缺席(`POST /sessions` 等还没收工的响应)时解成 null, 而不是抛。 */
    @Test
    fun acceptedPayloadWithoutReviewStatusDecodesToNull() {
        val payload = """
            {"session_id":"s1","revision":3,"stage":"review","status":"completed"}
        """.trimIndent()
        assertNull(json.decodeFromString<FinishMissionResponseDto>(payload).reviewStatus)
    }

    /**
     * `SessionView.review_status` 是复盘页的**轮询键**。合法三值 + 脏值 + 显式 null 都要解得开:
     * 它住在服务端 JSON 列里, 后端刻意声明成 `str | None` 而非字面量, 就是为了让脏数据降级成
     * "不可知"而不是把 `GET /sessions/{id}` 打成 500。脏值**原样透传**给界面层判断,
     * 解码处不猜; 只有空串与 null 收敛成 null(两者都不是一个状态)。
     */
    @Test
    fun sessionViewReviewStatusAcceptsEveryValueTheJsonColumnCanHold() {
        // 每个分支都要单独看一眼"有没有报告": 后端在脏值时会把它自己映射成 ready, 而**未收工**
        // 与**旧快照**都是 null。客户端对 null 的处置是"不再等", 对 generating 才是"接着轮"。
        val cases = mapOf(
            "\"generating\"" to "generating",
            "\"ready\"" to "ready",
            "\"failed\"" to "failed",
            // 脏值**原样透传**: 判断归 ReviewStateMachine, 解码处不猜(猜了就没人测得到)。
            "\"queued-by-a-future-backend\"" to "queued-by-a-future-backend",
            "null" to null,
            "\"  \"" to null
        )
        for ((raw, expected) in cases) {
            val payload = """
                {"session_id":"s1","scene_id":"sc","stage":"review","status":"completed",
                 "revision":12,"review":null,"review_status":$raw}
            """.trimIndent()
            val snapshot = json.decodeFromString<SessionViewDto>(payload).toDomain()
            assertEquals("review_status=$raw", expected, snapshot.reviewStatus)
        }
    }

    /** 整个键缺席(§P6 之前的快照)也要照解: `review_status` 只能是"不知道", 不能是崩。 */
    @Test
    fun sessionViewWithoutTheKeyAtAllDecodesToNull() {
        val payload = """
            {"session_id":"s1","scene_id":"sc","stage":"review","status":"completed",
             "revision":12}
        """.trimIndent()
        val snapshot = json.decodeFromString<SessionViewDto>(payload).toDomain()
        assertNull(snapshot.reviewStatus)
        assertNull(snapshot.review)
    }

    /**
     * 自动收工(到轮次上界)那条路径现在也带 `review_status`。这一条**最**要紧: 一天练到
     * 自然结束是每日最常见的收尾方式, 而它以前必然撞上 30s 读超时(客户端连跳转都跑不到)。
     */
    @Test
    fun autoFinishedMissionTurnCarriesThePollingKeyAndSkeleton() {
        val payload = """
            {"session_id":"s1","revision":20,"stage":"mission","status":"completed",
             "turn_index":14,"transcript":"Thanks!","reply":"Anytime.",
             "suggestion":"","polish":null,"sub_scores":{},"word_details":[],
             "speech_rate_wpm":null,"newly_done":[],"checklist":[],"cleared":true,
             "turn_count":14,"max_turns":14,"auto_finished":true,"finished":true,
             "ability_events":[],"source":"heuristic","llm_source":null,
             "costs_score":false,
             "review":{"session_id":"s1","scene_id":"scene_ordering_coffee",
               "title":"咖啡店点单","cleared":true,"overall":null,
               "dims":{"pronunciation":null,"grammar":null,"vocabulary":null,"fluency":null},
               "evidence_note_cn":"本场缺少可信评分证据, 暂无法给出总分。",
               "highlights":[],"improvements":[],"checklist":[],"transcript_pairs":[],
               "new_tokens":[],"ability_delta":{},"hints_used":0,
               "source":"heuristic","llm_source":null},
             "review_status":"generating"}
        """.trimIndent()
        val result = json.decodeFromString<MissionTurnResponseDto>(payload).toDomain()
        assertTrue(result.autoFinished)
        assertEquals("generating", result.reviewStatus)
        // 数值骨架是**跟着**回来的: 那一屏分数不欠 AI 一次调用。
        val report = result.review!!
        assertEquals("本场缺少可信评分证据, 暂无法给出总分。", report.evidenceNoteCn)
        assertNull(report.overall)
    }

    /**
     * 一轮普通对话(没收工)时这个键缺席, 领域层必须是 null —— 不是 "ready"。
     * 把"没听说过"读成一个真状态, 复盘页就会以为文案已经定稿。
     */
    @Test
    fun ordinaryMissionTurnHasNoReviewStatus() {
        val payload = """
            {"session_id":"s1","revision":9,"stage":"mission","status":"active",
             "turn_index":2,"transcript":"A medium coffee.","reply":"For here?",
             "suggestion":"","polish":null,"sub_scores":{},"word_details":[],
             "speech_rate_wpm":null,"newly_done":[],"checklist":[],"cleared":false,
             "turn_count":2,"max_turns":14,"auto_finished":false,"finished":false,
             "ability_events":[],"source":"llm","llm_source":"qwen3.8-max",
             "costs_score":false,"review":null}
        """.trimIndent()
        val result = json.decodeFromString<MissionTurnResponseDto>(payload).toDomain()
        assertNull(result.reviewStatus)
        assertNull(result.review)
    }

    /**
     * `evidence_note_cn` 的往返。缺席时必须是 "" 而不是崩: 没证据说明**是常态**(有证据时
     * 服务端就留空), 而界面拿"有没有这句话"决定圆环中心画分数、画说明, 还是退回破折号。
     */
    @Test
    fun reviewReportEvidenceNoteRoundTripsAndDefaultsToEmpty() {
        val withNote = """
            {"session_id":"s1","scene_id":"sc","title":"t","overall":null,
             "evidence_note_cn":"这场没有可信评分证据(讯飞/LLM 未配置)。"}
        """.trimIndent()
        val note = json.decodeFromString<ReviewReportDto>(withNote).toDomain()
        assertEquals("这场没有可信评分证据(讯飞/LLM 未配置)。", note.evidenceNoteCn)
        assertNull(note.overall)
        val without = """{"session_id":"s1","scene_id":"sc","title":"t"}"""
        assertEquals("", json.decodeFromString<ReviewReportDto>(without).toDomain().evidenceNoteCn)
    }

    /**
     * 数值骨架的**全景**形状(§P6 收工当场落库的那一份, 键与 `ReviewReport` 一一对应)。
     *
     * 锁的是两件事: 一, `overall`/四维可以为 null 而整份报告照解(无可信证据是真实存在的
     * 结果, 不是异常); 二, 这些数值**不欠** AI 文案 —— `highlights` 空着也要画得出分数,
     * 那正是复盘页第三态敢把圆环先摆出来的前提。
     */
    @Test
    fun decodesTheDeterministicSkeletonThatLandsBeforeTheCopy() {
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95",
             "scene_id":"scene_ordering_coffee","title":"咖啡店点单","cleared":false,
             "auto_finished":false,"turn_count":2,"max_turns":14,"overall":80.2,
             "dims":{"pronunciation":null,"grammar":79.0,"vocabulary":81.3,"fluency":null},
             "pronunciation_subs":{"pronunciation":null,"fluency":null,"completeness":null},
             "evidence_note_cn":"",
             "highlights":[],"improvements":[],
             "checklist":[{"id":"t1","desc_cn":"点一杯咖啡","hint_en":"","required":true,
               "done":true,"evidence":"ok","done_at_turn":1}],
             "transcript_pairs":[{"original":"Can I have a croissant?",
               "polished":"Can I change that to a large?",
               "explanation_cn":"换成大杯用 change ... to a large。","source":"translate"}],
             "new_tokens":["coffee","medium","add"],
             "ability_delta":{"pronunciation":null,"grammar":null,"vocabulary":null,
               "fluency":null},
             "hints_used":1,"source":"heuristic","llm_source":"stub"}
        """.trimIndent()
        val report = json.decodeFromString<ReviewReportDto>(payload).toDomain()
        assertEquals(80.2, report.overall!!, 0.01)
        assertNull(report.dims["pronunciation"])
        assertEquals(81.3, report.dims["vocabulary"]!!, 0.01)
        assertEquals("heuristic", report.source)
        assertEquals(1, report.transcriptPairs.size)
        assertEquals("换成大杯用 change ... to a large。", report.transcriptPairs[0].explanationCn)
        assertEquals(listOf("coffee", "medium", "add"), report.newTokens)
        assertFalse(report.cleared)
        assertEquals("", report.evidenceNoteCn)
    }
}
