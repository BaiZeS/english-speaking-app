package com.app.english.data.remote

import com.app.english.domain.model.ReviewReportData
import com.app.english.ui.scenes.taskProgressLabel
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * 用 2026-09-05 本机起服的真实响应样本(T7 采样, 见 zcode-report.md)锁 DTO 形状:
 * kotlinx 严格类型下, 后端字段类型/可空性漂移会在这里炸, 而不是在用户手机上。
 */
class SessionDtoRealSampleTest {
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

    @Test
    fun decodesRealReviewReportWithNullDims() {
        // POST /sessions/{id}/finish-mission 200(本机无讯飞 -> 发音/流利度无证据)。
        val payload = """
            {"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95","revision":11,
             "stage":"review","status":"completed",
             "report":{"session_id":"7dacd6e9-1653-4c42-82f1-e3aea298aa95",
               "scene_id":"scene_ordering_coffee","title":"咖啡店点单","cleared":false,
               "auto_finished":false,"turn_count":2,"max_turns":14,"overall":80.2,
               "dims":{"pronunciation":null,"grammar":79.0,"vocabulary":81.3,
                 "fluency":null},
               "pronunciation_subs":{"pronunciation":null,"fluency":null,
                 "completeness":null},
               "highlights":["实战里做成了 3 项沟通任务。"],
               "improvements":["还差必做沟通任务: 说明奶糖。"],
               "checklist":[{"id":"t1","desc_cn":"点一杯咖啡","hint_en":"","required":true,
                 "done":true,"evidence":"ok","done_at_turn":1}],
               "transcript_pairs":[{"original":"Can I have a croissant?",
                 "polished":"Can I change that to a large?",
                 "explanation_cn":"换成大杯用 change ... to a large。","source":"translate"}],
               "new_tokens":["coffee","medium","add"],
               "ability_delta":{"pronunciation":null,"grammar":null,"vocabulary":null,
                 "fluency":null},
               "hints_used":1,"source":"heuristic","llm_source":"stub"}}
        """.trimIndent()
        val response = json.decodeFromString<FinishMissionResponseDto>(payload)
        val report: ReviewReportData = response.report.toDomain()
        assertEquals(80.2, report.overall!!, 0.01)
        assertNull(report.dims["pronunciation"])
        assertEquals(81.3, report.dims["vocabulary"]!!, 0.01)
        assertEquals("heuristic", report.source)
        assertEquals(1, report.transcriptPairs.size)
        assertEquals("换成大杯用 change ... to a large。", report.transcriptPairs[0].explanationCn)
        assertFalse(report.cleared)
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
