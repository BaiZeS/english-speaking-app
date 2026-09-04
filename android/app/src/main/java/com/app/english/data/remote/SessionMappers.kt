package com.app.english.data.remote

import com.app.english.domain.model.BriefingProgress
import com.app.english.domain.model.BriefingStepState
import com.app.english.domain.model.ContinueSession
import com.app.english.domain.model.DrillGradeResult
import com.app.english.domain.model.DrillMistake
import com.app.english.domain.model.ExpressionEntry
import com.app.english.domain.model.FoundationStepSpec
import com.app.english.domain.model.GenerationJob
import com.app.english.domain.model.HintData
import com.app.english.domain.model.MissionRecovery
import com.app.english.domain.model.MissionSpecDetail
import com.app.english.domain.model.MissionTaskSpec
import com.app.english.domain.model.MissionTurn
import com.app.english.domain.model.MissionTurnLog
import com.app.english.domain.model.MissionTurnResult
import com.app.english.domain.model.NewlyDoneTask
import com.app.english.domain.model.PolishSuggestion
import com.app.english.domain.model.SceneCourseDetail
import com.app.english.domain.model.ScriptExchange
import com.app.english.domain.model.SessionSnapshot
import com.app.english.domain.model.TaskChip
import com.app.english.domain.model.VocabCard

/**
 * 会话状态机 / 生成任务 / 表达库的 DTO -> 领域模型映射(计划 §6.5)。
 * 全部是纯函数, `SessionMappersTest` 用真实后端样本锁形状。
 */

fun SceneCourseDto.toDomain(): SceneCourseDetail = SceneCourseDetail(
    id = id,
    source = source,
    category = category,
    title = title,
    subtitleEn = subtitleEn,
    goalText = goalText,
    level = level,
    estMinutes = estMinutes,
    briefCn = briefCn,
    vocab = vocab.map { it.toDomain() },
    briefing = briefing.map { it.toDomain() },
    mission = mission.toDomain(),
    skills = skills
)

fun VocabItemDto.toDomain(): VocabCard = VocabCard(
    word = word,
    ipa = ipa,
    meaningCn = meaningCn,
    exampleEn = exampleEn
)

fun FoundationStepDto.toDomain(): FoundationStepSpec = FoundationStepSpec(
    id = id,
    type = type,
    cnPrompt = cnPrompt,
    refText = refText,
    translationCn = translationCn,
    referenceAnswer = referenceAnswer,
    targetWord = targetWord,
    acceptNotes = acceptNotes
)

fun MissionSpecDto.toDomain(): MissionSpecDetail = MissionSpecDetail(
    personaCn = personaCn,
    userRoleCn = userRoleCn,
    contextCn = contextCn,
    openingA = openingA,
    openingACn = openingACn,
    exchanges = exchanges.map { ScriptExchange(a = it.a, b = it.b, aCn = it.aCn, bCn = it.bCn) },
    tasks = tasks.map {
        MissionTaskSpec(
            id = it.id,
            descCn = it.descCn,
            hintEn = it.hintEn,
            hintCn = it.hintCn,
            required = it.required
        )
    },
    maxTurns = maxTurns
)

fun DrillGradeDto.toDomain(): DrillGradeResult = DrillGradeResult(
    stepId = stepId,
    stepType = stepType,
    score = score,
    passed = passed,
    passScore = passScore,
    feedbackCn = feedbackCn,
    pronunciation = pronunciation,
    fluency = fluency,
    completeness = completeness,
    grammar = grammar,
    vocabulary = vocabulary,
    transcript = transcript,
    wordDetails = wordDetails.map {
        com.app.english.domain.model.WordScore(it.word, it.score, it.ipa)
    },
    keyPointsHit = keyPointsHit,
    mistakes = mistakes.map { DrillMistake(it.sourceCn, it.said, it.better, it.explanationCn) },
    source = source,
    llmSource = llmSource
)

fun BriefingProgressDto.toDomain(): BriefingProgress = BriefingProgress(
    total = total,
    done = done,
    passed = passed,
    skipped = skipped,
    skipsUsed = skipsUsed,
    skipLimit = skipLimit,
    skipsRemaining = skipsRemaining,
    nextStepId = nextStepId,
    unlockedMission = unlockedMission,
    steps = steps.map { step ->
        BriefingStepState(
            id = step.id,
            index = step.index,
            type = step.type,
            status = step.status,
            attempts = step.attempts,
            bestScore = step.bestScore,
            lastScore = step.lastScore,
            lastSource = step.lastSource
        )
    }
)

fun PolishDto.toDomain(): PolishSuggestion =
    PolishSuggestion(original = original, polished = polished, explanationCn = explanationCn)

fun TranscriptPairDto.toDomain(): PolishSuggestion =
    PolishSuggestion(original = original, polished = polished, explanationCn = explanationCn)

fun MissionTaskViewDto.toDomain(): TaskChip = TaskChip(
    id = id,
    descCn = descCn,
    hintEn = hintEn,
    required = required,
    done = done,
    evidence = evidence
)

fun SessionViewDto.toDomain(): SessionSnapshot = SessionSnapshot(
    sessionId = sessionId,
    sceneId = sceneId,
    stage = stage,
    status = status,
    revision = revision,
    briefing = briefing.toDomain(),
    mission = mission?.toDomain(),
    review = review?.toDomain(),
    course = course?.toDomain()
)

fun MissionSnapshotDto.toDomain(): MissionRecovery = MissionRecovery(
    openingA = opening?.a.orEmpty(),
    openingACn = opening?.aCn.orEmpty(),
    turns = turns.map { turn ->
        MissionTurnLog(
            turnIndex = turn.index,
            transcript = turn.userText,
            reply = turn.reply,
            polish = turn.polish?.toDomain(),
            costsScore = turn.costsScore
        )
    },
    tasks = tasks.map { it.toDomain() },
    turnCount = turnCount,
    maxTurns = maxTurns
)

fun MissionTurnResponseDto.toDomain(): MissionTurnResult = MissionTurnResult(
    turn = MissionTurn(
        turnIndex = turnIndex,
        transcript = transcript,
        reply = reply,
        suggestion = suggestion,
        polish = polish?.toDomain(),
        newlyDone = newlyDone.map { NewlyDoneTask(it.id, it.evidence) },
        costsScore = costsScore
    ),
    checklist = checklist.map { it.toDomain() },
    cleared = cleared,
    turnCount = turnCount,
    maxTurns = maxTurns,
    autoFinished = autoFinished,
    finished = finished,
    costsScore = costsScore,
    source = source,
    llmSource = llmSource,
    review = review?.toDomain()
)

fun ReviewReportDto.toDomain(): com.app.english.domain.model.ReviewReportData =
    com.app.english.domain.model.ReviewReportData(
        sessionId = sessionId,
        sceneId = sceneId,
        title = title,
        cleared = cleared,
        autoFinished = autoFinished,
        turnCount = turnCount,
        maxTurns = maxTurns,
        overall = overall,
        dims = dims,
        pronunciationSubs = pronunciationSubs,
        highlights = highlights,
        improvements = improvements,
        checklist = checklist.map { it.toDomain() },
        transcriptPairs = transcriptPairs.map { it.toDomain() },
        newTokens = newTokens,
        abilityDelta = abilityDelta,
        hintsUsed = hintsUsed,
        source = source,
        llmSource = llmSource
    )

fun HintResponseDto.toHintData(): HintData = HintData(
    taskId = hint.taskId,
    descCn = hint.descCn,
    hintEn = hint.hintEn,
    scriptLine = hint.scriptLine,
    noteCn = hint.noteCn
)

fun SessionSummaryDto.toDomain(): ContinueSession = ContinueSession(
    sessionId = sessionId,
    sceneId = sceneId,
    title = title,
    level = level,
    stage = stage,
    doneSteps = doneSteps,
    totalSteps = totalSteps,
    unlockedMission = unlockedMission
)

fun GenerationJobDto.toDomain(): GenerationJob = GenerationJob(
    jobId = jobId,
    status = status,
    progress = progress,
    stageText = stageText,
    sceneId = sceneId,
    error = error
)

fun ExpressionDto.toDomain(): ExpressionEntry = ExpressionEntry(
    id = id,
    polished = polished,
    original = original,
    explanationCn = explanationCn,
    sourceLabel = sourceLabel,
    sceneId = sceneId,
    createdAt = createdAt
)
