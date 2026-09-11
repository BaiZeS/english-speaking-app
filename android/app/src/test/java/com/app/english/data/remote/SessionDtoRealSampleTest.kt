package com.app.english.data.remote

import com.app.english.domain.model.ReviewReportData
import com.app.english.ui.scenes.subScoreReadout
import com.app.english.ui.scenes.taskProgressLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 用 2026-09-05 本机起服的真实响应样本(T7 采样, 见 zcode-report.md)锁 DTO 形状:
 * kotlinx 严格类型下, 后端字段类型/可空性漂移会在这里炸, 而不是在用户手机上。
 */
class SessionDtoRealSampleTest {
    companion object {
        /** 状态取值表用模板, 免得把转义引号嵌进三引号串里看不清。 */
        private const val REVIEW_STATUS_PLACEHOLDER = "@@STATUS@@"

        private val SESSION_VIEW_WITH_STATUS = """
            {"session_id":"s1","scene_id":"sc","stage":"review","status":"completed",
             "revision":12,"review":null,"review_status":$REVIEW_STATUS_PLACEHOLDER,"course":null}
        """.trimIndent()
    }
    private val json = kotlinx.serialization.json.Json {
        ignoreUnknownKeys = true
        coerceInputValues = true
        explicitNulls = false
    }

    @Test
    fun decodesRealSessionCreateResponse() {
        // POST /sessions 201: course 快照 + briefing 清单(节选自 scene_ordering_coffee)。
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95","kind":"scene_course",
             "scene_id":"scene_ordering_coffee","stage":"briefing","status":"active",
             "revision":1,"created_at":"2026-09-04T18:10:00+00:00",
             "last_active_at":"2026-09-04T18:10:00+00:00",
             "briefing":{"total":6,"done":0,"passed":0,"skipped":0,"skips_used":0,
               "skip_limit":2,"skips_remaining":2,"next_step_id":"f1",
               "unlocked_mission":false,
               "steps":[{"id":"f1","index":0,"type":"read_along","status":"pending",
                 "attempts":0,"best_score":null,"last_score":null,"last_source":null,
                 "last_grade":null}]},
             "mission":{},
             "review":null,
             "course":{"schema_version":1,"id":"scene_ordering_coffee","source":"curated",
               "category":"daily","title":"咖啡店点单","subtitle_en":"Ordering at a cafe",
               "goal_text":"","level":"A2","est_minutes":8,"brief_cn":"练习点单。",
               "vocab":[{"word":"coffee","ipa":"/ˈkɔfi/","meaning_cn":"n. 咖啡",
                 "example_en":"Can I get a coffee?"}],
               "briefing":[{"id":"f3","type":"retell","cn_prompt":"把这单说出来。",
                 "ref_text":"I want a medium coffee.","translation_cn":"我要中杯咖啡。",
                 "reference_answer":"Medium coffee.","target_word":"","accept_notes":"杯型即可。"}],
               "mission":{"persona_cn":"咖啡店店员","user_role_cn":"顾客","context_cn":"点单",
                 "opening_a":"Hi there.","opening_a_cn":"你好。",
                 "exchanges":[{"a":"Hi there.","b":"A medium coffee.","a_cn":"你好。",
                   "b_cn":"中杯咖啡。"}],
                 "tasks":[{"id":"t1","desc_cn":"点一杯咖啡","hint_en":"Can I get a coffee?",
                   "hint_cn":"直接说 want","required":true}],
                 "max_turns":14},
               "skills":["pronunciation"]}}
        """.trimIndent()
        val view = json.decodeFromString<SessionViewDto>(payload)
        assertEquals("briefing", view.stage)
        assertEquals(6, view.briefing.total)
        assertEquals("f1", view.briefing.nextStepId)
        assertEquals(1, view.briefing.steps.size)
        val course = view.course!!
        assertEquals("咖啡店点单", course.title)
        assertEquals(14, course.mission.maxTurns)
        assertEquals("retell", course.briefing[0].type)
        // mission 是空 dict(首轮之前): kotlinx 解码成全默认实例而非 null,
        // 恢复逻辑以 turns 是否为空 + stage 判断, 不依赖这里的 null。
        assertTrue(view.mission?.turns.isNullOrEmpty())
        assertNull(view.review)
    }

    @Test
    fun decodesRealStepAttemptResponse() {
        // POST /sessions/{id}/step 200(retell 文本作答, qwen3.8-max 判分)。
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95","revision":5,
             "stage":"briefing","status":"active",
             "grade":{"step_id":"f3","step_type":"retell","score":100.0,"passed":true,
               "pass_score":60.0,"feedback_cn":"要点齐全。",
               "pronunciation":null,"fluency":null,"completeness":null,"grammar":null,
               "vocabulary":100.0,"transcript":"I want a medium coffee.",
               "word_details":[],"key_points_hit":["medium coffee","to go"],
               "mistakes":[],"speech_rate_wpm":null,"ise_ref_mode":null,
               "source":"llm","llm_source":"qwen3.8-max"},
             "briefing":{"total":6,"done":1,"passed":1,"skipped":0,"skips_used":0,
               "skip_limit":2,"skips_remaining":2,"next_step_id":"f4",
               "unlocked_mission":false,
               "steps":[{"id":"f3","index":2,"type":"retell","status":"passed",
                 "attempts":1,"best_score":100.0,"last_score":100.0,
                 "last_source":"llm","last_grade":null}]},
             "unlocked_mission":false,
             "ability_events":[{"dimension":"vocabulary","score":100.0,"source":"llm",
               "weight":1.0,"ise_ref_mode":null}]}
        """.trimIndent()
        val response = json.decodeFromString<StepAttemptResponseDto>(payload)
        assertTrue(response.grade.passed)
        assertEquals("llm", response.grade.source)
        assertEquals("qwen3.8-max", response.grade.llmSource)
        assertEquals(2, response.grade.keyPointsHit.size)
        assertEquals("f4", response.briefing.nextStepId)
        assertEquals("vocabulary", response.abilityEvents[0].dimension)
        val domain = response.grade.toDomain()
        assertTrue(domain.isRealEvidence)
    }

    @Test
    fun decodesRealSkipGradeWithSkipSource() {
        val payload = """
            {"session_id":"s1","revision":2,"stage":"briefing","status":"active",
             "grade":{"step_id":"f1","step_type":"read_along","score":0.0,"passed":true,
               "pass_score":60.0,"feedback_cn":"已跳过这一步 (每场最多跳 2 步)。",
               "pronunciation":null,"fluency":null,"completeness":null,"grammar":null,
               "vocabulary":null,"transcript":null,"word_details":[],"key_points_hit":[],
               "mistakes":[],"speech_rate_wpm":null,"ise_ref_mode":null,"source":"stub",
               "llm_source":"skip"},
             "briefing":{"total":6,"done":1,"passed":0,"skipped":1,"skips_used":1,
               "skip_limit":2,"skips_remaining":1,"next_step_id":"f2",
               "unlocked_mission":false,"steps":[]},
             "unlocked_mission":false,"ability_events":[]}
        """.trimIndent()
        val response = json.decodeFromString<StepAttemptResponseDto>(payload)
        assertEquals("skip", response.grade.llmSource)
        assertFalse(response.grade.toDomain().isRealEvidence)
    }

    @Test
    fun decodesRealMissionTurnResponse() {
        // POST /sessions/{id}/mission 200(第一轮, qwen 判分, t1 新完成)。
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95","revision":8,
             "stage":"mission","status":"active","turn_index":1,
             "transcript":"Hi, can I get a medium coffee?",
             "reply":"Okay, medium coffee—for here or to go?",
             "suggestion":"To go, please.","polish":null,
             "sub_scores":{"pronunciation":null,"grammar":95.0,"vocabulary":88.0,
               "fluency":null},
             "word_details":[],"speech_rate_wpm":null,
             "newly_done":[{"id":"t1","evidence":"学员点了 medium coffee。"}],
             "checklist":[{"id":"t1","desc_cn":"点一杯咖啡并说清杯型",
               "hint_en":"Can I get a medium coffee?","required":true,"done":true,
               "evidence":"学员点了 medium coffee。","done_at_turn":1},
              {"id":"t2","desc_cn":"说明奶糖","hint_en":"","required":true,"done":false,
               "evidence":"","done_at_turn":null}],
             "cleared":false,"turn_count":1,"max_turns":14,"auto_finished":false,
             "finished":false,"ability_events":[],"source":"llm",
             "llm_source":"qwen3.8-max","costs_score":false,"review":null}
        """.trimIndent()
        val response = json.decodeFromString<MissionTurnResponseDto>(payload)
        assertEquals(1, response.turnIndex)
        assertEquals(1, response.newlyDone.size)
        assertTrue(response.checklist[0].done)
        assertEquals("llm", response.source)
        val result = response.toDomain()
        assertEquals("1/2", taskProgressLabel(result.checklist))
        assertTrue(result.checklist.first().done)
        assertFalse(result.cleared)
    }

    /**
     * 实战轮的 `sub_scores` 曾被映射层丢掉 -> 语音说完在聊天流里看不到任何发音证据,
     * 和打基础是同一个病。这里锁住"到了领域层", 以及 null 维度**没被补成 0**。
     */
    @Test
    fun missionTurnCarriesPerTurnSpeechEvidence() {
        val payload = """
            {"session_id":"s2","revision":9,"stage":"mission","status":"active",
             "turn_index":2,"transcript":"Can I get a medium coffee?",
             "reply":"Sure, for here?","suggestion":"","polish":null,
             "sub_scores":{"pronunciation":76.5,"grammar":null,"vocabulary":88.0,
               "fluency":null},
             "word_details":[{"word":"croissant","score":34.0,"ipa":"/kwaˈsɑ̃/"}],
             "speech_rate_wpm":137.6,"newly_done":[],"checklist":[],
             "cleared":false,"turn_count":2,"max_turns":14,"auto_finished":false,
             "finished":false,"ability_events":[],"source":"llm",
             "llm_source":"qwen3.8-max","costs_score":false,"review":null}
        """.trimIndent()
        val turn = json.decodeFromString<MissionTurnResponseDto>(payload).toDomain().turn
        assertEquals(4, turn.subScores.size)
        assertEquals(76.5, turn.subScores["pronunciation"]!!, 0.01)
        assertNull(turn.subScores["grammar"])
        assertEquals(1, turn.wordDetails.size)
        assertEquals(137.6, turn.speechRateWpm!!, 0.01)
        // 界面读数: 只有有证据的两个维度, 顺序固定。
        assertEquals(
            listOf("发音" to 76.5, "词汇" to 88.0),
            subScoreReadout(turn.subScores).map { it.label to it.score }
        )
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
        assertEquals("generating", json.decodeFromString<FinishMissionResponseDto>(payload).reviewStatus)
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
        val cases = mapOf(
            "\"generating\"" to "generating",
            "\"ready\"" to "ready",
            "\"failed\"" to "failed",
            "\"queued-by-a-future-backend\"" to "queued-by-a-future-backend",
            "null" to null,
            "\"\"" to null,
            "\"  \"" to null
        )
        for ((raw, expected) in cases) {
            val payload = SESSION_VIEW_WITH_STATUS.replace("$REVIEW_STATUS_PLACEHOLDER", raw)
            val mapped = json.decodeFromString<SessionViewDto>(payload).toDomain().reviewStatus
            assertEquals("review_status=$raw", expected, mapped)
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
     * `step.last_grade` 曾被映射层悄悄丢掉: DTO 解得出来、`BriefingStepState` 没有这个
     * 字段, 于是重进/崩溃恢复后每一步的反馈(逐词分、转写、建议)全部消失, 只剩一个数。
     * 后端 `_apply_step_grade` 是**特意**逐步存整份评分的, 这里锁住它确实到手。
     */
    @Test
    fun briefingStepCarriesItsPersistedWholeGrade() {
        val payload = """
            {"total":2,"done":0,"passed":0,"skipped":0,"skips_used":0,
             "skip_limit":2,"skips_remaining":2,"next_step_id":"f1",
             "unlocked_mission":false,
             "steps":[{"id":"f1","index":0,"type":"read_along","status":"pending",
               "attempts":1,"best_score":48.0,"last_score":48.0,"last_source":"xunfei",
               "last_grade":{"step_id":"f1","step_type":"read_along","score":48.0,
                 "passed":false,"pass_score":60.0,"feedback_cn":"morning 的尾音收住了。",
                 "pronunciation":45.0,"fluency":52.0,"completeness":null,
                 "grammar":null,"vocabulary":null,
                 "transcript":"Good morning everyone",
                 "word_details":[{"word":"good","score":88.0,"ipa":"/ɡʊd/"},
                   {"word":"morning","score":31.0,"ipa":"/ˈmɔːnɪŋ/"}],
                 "key_points_hit":[],"mistakes":[],"speech_rate_wpm":96.0,
                 "ise_ref_mode":"read_along","source":"xunfei","llm_source":null}}]}
        """.trimIndent()
        val progress = json.decodeFromString<BriefingProgressDto>(payload).toDomain()
        val grade = progress.steps.first().lastGrade
        assertNotNull(grade)
        assertEquals(48.0, grade!!.score, 0.01)
        assertFalse(grade.passed)
        assertEquals("Good morning everyone", grade.transcript)
        assertEquals(2, grade.wordDetails.size)
        assertEquals("/ˈmɔːnɪŋ/", grade.wordDetails[1].ipa)
        // null 维度保持 null: "这一轮没测到"不是 0 分, 界面据此跳过不画。
        assertNull(grade.completeness)
        assertTrue(grade.isRealEvidence)
    }

    @Test
    fun decodesRealJobViewAndExpressions() {
        // GET /scenes/jobs/{id} 的 running 与 ready 终态 + 表达库列表(真实样本)。
        val running = json.decodeFromString<GenerationJobDto>(
            """{"job_id":"11241c5b","status":"running","progress":0.05,
                "stage_text":"理解学习目标…","scene_id":null,"error":null}"""
        )
        assertEquals("running", running.status)
        assertNull(running.sceneId)
        val ready = json.decodeFromString<GenerationJobDto>(
            """{"job_id":"11241c5b","status":"ready","progress":1.0,
                "stage_text":"生成完成","scene_id":"scene_g36f56ad32f09","error":null}"""
        )
        assertEquals("scene_g36f56ad32f09", ready.sceneId)
        val expression = json.decodeFromString<ExpressionDto>(
            """{"id":"b782e537","polished":"Can I change that to a large?",
                "original":"Can I have a croissant?",
                "explanation_cn":"换成大杯用 change ... to a large。",
                "source_label":"mission","scene_id":"scene_ordering_coffee",
                "session_id":"","created_at":"2026-09-04T18:17:35.447780+00:00"}"""
        )
        assertEquals("mission", expression.sourceLabel)
    }
}
