package com.app.english.data.remote

import com.app.english.domain.model.HistoryItem
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.LessonSummary
import com.app.english.domain.model.Line
import com.app.english.domain.model.Role
import com.app.english.domain.model.ScoreResult
import com.app.english.domain.model.WordScore

fun LessonSummaryDto.toDomain(): LessonSummary = LessonSummary(
    id = id,
    book = book,
    lessonNo = lessonNo,
    title = title,
    roleCount = roleCount,
    durationS = durationS
)

fun LessonDetailDto.toDomain(): LessonDetail = LessonDetail(
    id = id,
    book = book,
    lessonNo = lessonNo,
    title = title,
    roles = roles.map { role -> role.toDomainRole() }
)

private fun RoleDto.toDomainRole(): Role = Role(
    name = name,
    lines = lines.map { line -> line.toDomainLine() }
)

private fun LineDto.toDomainLine(): Line = Line(
    id = id,
    text = text,
    translation = translation,
    ipa = ipa
)

fun ScoreResponseDto.toDomain(): ScoreResult = ScoreResult(
    total = total,
    pronunciation = pronunciation,
    fluency = fluency,
    completeness = completeness,
    wordDetails = wordDetails.map { WordScore(it.word, it.score, it.ipa) },
    suggestion = suggestion
)

fun HistoryItemDto.toDomain(): HistoryItem = HistoryItem(
    id = id,
    lessonId = lessonId,
    lineId = lineId,
    scoreTotal = scoreTotal,
    scorePronunciation = scorePronunciation,
    scoreFluency = scoreFluency,
    scoreCompleteness = scoreCompleteness,
    createdAt = createdAt
)


fun DialogueLineDto.toDomain(): com.app.english.domain.model.DialogueLine =
    com.app.english.domain.model.DialogueLine(
        id = id,
        role = role,
        text = text,
        translation = translation,
        isUser = isUser
    )

fun DialogueGenerateResponseDto.toDomain(): com.app.english.domain.model.DialogueSession =
    com.app.english.domain.model.DialogueSession(
        sceneId = sceneId,
        status = status,
        title = title,
        lines = lines.map { it.toDomain() },
        suggestedReply = suggestedReply
    )

fun DialogueTurnResponseDto.toDomain(): com.app.english.domain.model.DialogueTurn =
    com.app.english.domain.model.DialogueTurn(
        replyText = replyText,
        suggestedReply = suggestedReply,
        recognizedText = recognizedText,
        replyAudioUrl = replyAudioUrl
    )
