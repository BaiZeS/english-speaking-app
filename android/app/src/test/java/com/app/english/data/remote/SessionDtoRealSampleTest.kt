package com.app.english.data.remote

import com.app.english.ui.scenes.speechStripOf
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

    // ====== §A3/§A4: 实战轮判分移出请求 + D4 双语 (真实形状样本) ======

    /**
     * 新形状的一轮: 台词与双语当场就有, 润色/语法词汇分**这一轮为 null** ——
     * `grading_status="pending"` 说的就是这件事 (判分在后台作业里)。
     *
     * 顺带钉住 T3 审查留下的那条: `source="pending"` **不是**降级信号, 界面上不许因此
     * 挂「非真实评测」横幅; 真降级由 `mission.turns[].source` 在判分落定后才说得清。
     */
    @Test
    fun decodesMissionTurnWithBilingualAndPendingGrading() {
        val payload = """
            {"session_id":"s3","revision":9,"stage":"mission","status":"active",
             "turn_index":2,"transcript":"I went hiking with my friends.",
             "reply":"Nice! Which trail did you take?",
             "suggestion":"We took the river trail.",
             "reply_cn":"不错！你们走的哪条路线？",
             "suggestion_cn":"我们走的河边那条路线。",
             "learner_cn":"我和朋友去徒步了。",
             "polish":null,
             "sub_scores":{"pronunciation":71.0,"grammar":null,"vocabulary":null,
               "fluency":null},
             "word_details":[],"speech_rate_wpm":null,"newly_done":[],"checklist":[],
             "cleared":false,"turn_count":2,"max_turns":14,"auto_finished":false,
             "finished":false,"ability_events":[],"source":"pending",
             "llm_source":"qwen3.8-flash","costs_score":false,
             "grading_status":"pending","review":null}
        """.trimIndent()
        val response = json.decodeFromString<MissionTurnResponseDto>(payload)
        assertEquals("pending", response.gradingStatus)
        assertNull(response.polish)
        val result = response.toDomain()
        assertEquals("pending", result.gradingStatus)
        assertEquals("pending", result.turn.gradingStatus)
        assertEquals("不错！你们走的哪条路线？", result.turn.replyCn)
        assertEquals("我们走的河边那条路线。", result.turn.suggestionCn)
        assertEquals("我和朋友去徒步了。", result.turn.learnerCn)
        // 判分未落时语法/词汇仍然是 null —— 不是 0, 界面据此跳过不画那一维。
        assertNull(result.turn.subScores["grammar"])
        assertEquals(71.0, result.turn.subScores["pronunciation"]!!, 0.01)
    }

    /** 老形状(没有三个中文键、没有 grading_status)仍要 decode 到安全的缺省。 */
    @Test
    fun legacyMissionTurnWithoutBilingualKeysDecodesToDefaults() {
        val payload = """
            {"session_id":"s4","revision":9,"stage":"mission","status":"active",
             "turn_index":1,"transcript":"Hello","reply":"Hi there!",
             "suggestion":"","polish":null,"sub_scores":{},"word_details":[],
             "newly_done":[],"checklist":[],"cleared":false,"turn_count":1,
             "max_turns":14,"auto_finished":false,"finished":false,
             "ability_events":[],"source":"llm","costs_score":false,"review":null}
        """.trimIndent()
        val result = json.decodeFromString<MissionTurnResponseDto>(payload).toDomain()
        assertEquals("", result.turn.replyCn)
        assertEquals("", result.turn.suggestionCn)
        assertEquals("", result.turn.learnerCn)
        assertEquals("", result.turn.gradingStatus)
        assertNull(result.gradingStatus)
        // 界面读数: 三个中文键全空 -> 那三行不渲染 (D5), 不是三个空行。
        assertTrue(result.turn.replyCn.isBlank())
    }

    /** `GET /sessions/{id}` 顶层的判分键 + 老快照(没有这个键) -> null = 不可知。 */
    @Test
    fun sessionViewCarriesGradingStatusAndToleratesItsAbsence() {
        val pending = json.decodeFromString<SessionViewDto>(
            SESSION_VIEW_WITH_STATUS.replace(REVIEW_STATUS_PLACEHOLDER, "\"generating\"")
                .replace("\"review\":null,", "\"review\":null,\"grading_status\":\"pending\",")
        )
        assertEquals("pending", pending.gradingStatus)
        assertEquals("pending", pending.toDomain().gradingStatus)

        val legacy = json.decodeFromString<SessionViewDto>(
            SESSION_VIEW_WITH_STATUS.replace(REVIEW_STATUS_PLACEHOLDER, "null")
        )
        assertNull(legacy.gradingStatus)
        assertNull(legacy.toDomain().gradingStatus)
        // 空串与缺键同义 (JSON 列里的脏值要能当"不可知"处理, 不许当 pending 用)。
        val blank = json.decodeFromString<SessionViewDto>(
            SESSION_VIEW_WITH_STATUS.replace(REVIEW_STATUS_PLACEHOLDER, "null")
                .replace("\"review\":null,", "\"review\":null,\"grading_status\":\"  \",")
        )
        assertNull(blank.toDomain().gradingStatus)
    }

    /**
     * 恢复通道(`GET /sessions/{id}` 的 `mission.turns[]`)必须带齐逐轮双语 + 判分槽位 +
     * 发音证据 —— 否则"重进实战页只剩英文"与"没读准的词消失"这两条会重新出现。
     */
    @Test
    fun missionSnapshotTurnsCarryBilingualEvidenceAndGradingSlot() {
        val payload = """
            {"opening":{"a":"Hi there.","a_cn":"你好。"},
             "turns":[
               {"index":1,"user_text":"I went hiking.","reply":"Nice! Which trail?",
                "suggestion":"We took the river trail.","reply_cn":"不错！哪条路线？",
                "suggestion_cn":"我们走的河边那条路线。","learner_cn":"我去徒步了。",
                "polish":{"original":"I go hiking","polished":"I went hiking",
                  "explanation_cn":"过去时。","polished_cn":"我去徒步了。"},
                "sub_scores":{"pronunciation":66.0,"grammar":90.0,"vocabulary":null,
                  "fluency":null},
                "word_details":[{"word":"hiking","score":31.0,"ipa":"/ˈhaɪkɪŋ/"}],
                "speech_rate_wpm":118.0,"costs_score":false,"source":"llm",
                "grading":{"status":"ready","at":"2026-10-08T10:00:00+00:00"}},
               {"index":2,"user_text":"It was great.","reply":"Sounds fun!",
                "suggestion":"","polish":null,"sub_scores":{},"word_details":[],
                "costs_score":false,"source":"pending",
                "grading":{"status":"pending","at":"2026-10-08T10:01:00+00:00"}}],
             "tasks":[{"id":"t1","desc_cn":"说清路线","hint_en":"We took the river trail.",
               "hint_cn":"用 took 说路线","required":true,"done":true,
               "evidence":"说了路线","done_at_turn":1}],
             "turn_count":2,"max_turns":14,"cleared":false,"finished":false,
             "hints_used":0,"grading":{"status":"pending","turn":2}}
        """.trimIndent()
        val recovery = json.decodeFromString<MissionSnapshotDto>(payload).toDomain()
        assertEquals("你好。", recovery.openingACn)
        val graded = recovery.turns[0]
        assertEquals("不错！哪条路线？", graded.replyCn)
        assertEquals("我们走的河边那条路线。", graded.suggestionCn)
        assertEquals("我去徒步了。", graded.learnerCn)
        assertEquals("ready", graded.gradingStatus)
        assertEquals("我去徒步了。", graded.polish?.polishedCn)
        // 逐词染色与维度分都到得了界面 (以前这一段被边界丢掉)。
        assertEquals(66.0, graded.subScores["pronunciation"]!!, 0.01)
        assertEquals(118.0, graded.speechRateWpm!!, 0.01)
        assertEquals(
            listOf("发音" to 66.0, "语法" to 90.0),
            subScoreReadout(graded.subScores).map { it.label to it.score }
        )
        // 逐词染色: 落在红带的词就是界面上"没读准"的那几个。
        assertEquals(
            listOf("hiking"),
            speechStripOf(graded.subScores, graded.wordDetails, graded.speechRateWpm)?.weakWords
        )
        val pending = recovery.turns[1]
        assertEquals("pending", pending.gradingStatus)
        assertEquals("", pending.replyCn)
        // chips 的中文提示 (库内早有, T2 起才随视图下发)。
        assertEquals("用 took 说路线", recovery.tasks.single().hintCn)
    }

    /** 提示卡: `hint_cn` / `script_line_cn` 两键都要到手 (以前边界把库里中文整条丢掉)。 */
    @Test
    fun decodesHintPayloadWithBothChineseLines() {
        val payload = """
            {"session_id":"s5","revision":3,"stage":"mission","status":"active",
             "hint":{"task_id":"t2","desc_cn":"说明奶糖","hint_en":"No sugar, please.",
               "hint_cn":"直接说 no sugar","script_line":"Just a little sugar.",
               "script_line_cn":"只要一点点糖。","note_cn":"先把要求说清楚"},
             "costs_score":true,"hints_used":1}
        """.trimIndent()
        val hint = json.decodeFromString<HintResponseDto>(payload).toHintData()
        assertEquals("直接说 no sugar", hint.hintCn)
        assertEquals("只要一点点糖。", hint.scriptLineCn)
        assertEquals("No sugar, please.", hint.hintEn)
        assertEquals("说明奶糖", hint.descCn)
    }
}
