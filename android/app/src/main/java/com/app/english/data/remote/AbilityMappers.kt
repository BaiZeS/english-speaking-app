package com.app.english.data.remote

import com.app.english.domain.model.AbilityProfile
import com.app.english.domain.model.AbilityTrajectoryPoint
import com.app.english.domain.model.AssessmentAnswerOutcome
import com.app.english.domain.model.AssessmentBank
import com.app.english.domain.model.AssessmentJudgement
import com.app.english.domain.model.AssessmentQuestion
import com.app.english.domain.model.AssessmentRadarAxis
import com.app.english.domain.model.AssessmentSession
import com.app.english.domain.model.PolishOutcome
import com.app.english.domain.model.PolishSuggestion

/** 测评/画像/润色 DTO -> 领域模型的纯映射(kotlinx 严格类型, 可 JVM 单测)。 */

fun AssessmentQuestionDto.toDomain(): AssessmentQuestion = AssessmentQuestion(
    id = id,
    no = no,
    type = type,
    cefrAnchor = cefrAnchor,
    cnPrompt = cnPrompt,
    displayText = displayText,
    translationCn = translationCn,
    seconds = seconds
)

fun AssessmentBankDto.toDomain(): AssessmentBank = AssessmentBank(
    total = total,
    questions = questions.map { it.toDomain() }
)

fun AssessmentStartResponseDto.toDomain(): AssessmentSession = AssessmentSession(
    attemptId = attemptId,
    total = total,
    questions = questions.map { it.toDomain() }
)

fun AssessmentAnswerResponseDto.toDomain(): AssessmentAnswerOutcome = AssessmentAnswerOutcome(
    questionNo = questionNo,
    answersCount = answersCount,
    total = total,
    transcript = transcript
)

fun AssessmentRadarAxisDto.toDomain(): AssessmentRadarAxis = AssessmentRadarAxis(
    dimension = dimension,
    score = score,
    max = max,
    n = n
)

fun AssessmentCompleteResponseDto.toDomain(): AssessmentJudgement = AssessmentJudgement(
    attemptId = attemptId,
    cefr = cefr,
    dims = dims,
    radar = radar.map { it.toDomain() },
    rationaleCn = rationaleCn,
    pronunciationSource = pronunciationSource,
    source = source,
    cefrLevel = cefrLevel
)

fun AbilityResponseDto.toDomain(): AbilityProfile = AbilityProfile(
    pronunciation = profile["pronunciation"],
    grammar = profile["grammar"],
    vocabulary = profile["vocabulary"],
    fluency = profile["fluency"],
    sampleCounts = n,
    cefrLevel = cefrLevel,
    assessmentCefr = assessmentCefr,
    bandLocked = bandLocked,
    derivedLevel = derivedLevel,
    days = days,
    trajectory = trajectory.map { point ->
        AbilityTrajectoryPoint(
            date = point.date,
            pronunciation = point.pronunciation,
            grammar = point.grammar,
            vocabulary = point.vocabulary,
            fluency = point.fluency,
            events = point.events
        )
    },
    realEvents = realEvents,
    userFound = userFound
)

fun PolishResponseDto.toDomain(): PolishOutcome = PolishOutcome(
    polish = polish?.toSuggestion(),
    source = source,
    noteCn = noteCn,
    expressionId = expressionId
)

private fun PolishDto.toSuggestion(): PolishSuggestion = PolishSuggestion(
    original = original,
    polished = polished,
    explanationCn = explanationCn
)
