package com.app.english.data.remote

import com.app.english.domain.model.ChatGrade
import com.app.english.domain.model.ChatMessage
import com.app.english.domain.model.ChatThread
import com.app.english.domain.model.ThreadSummary

/**
 * 线程 DTO -> 领域模型。
 *
 * 这一层之所以单独成文件: `doc.messages` 是**客户端渲染的唯一真相**, 所以"后端字段名 ->
 * UI 读的东西"这条映射是产品契约的一部分, 不是随手转个手。特别是 [toDomain] 对
 * `grade` 的处理 —— 缺轴 = 这一轮没有那个维度的证据, 不许补 0。
 */
fun ThreadViewDto.toDomain(): ChatThread = ChatThread(
    id = id,
    sceneId = sceneId,
    turnCount = turnCount,
    gradingStatus = gradingStatus,
    beatIndex = beatIndex,
    messages = messages.map { it.toDomain() }
)

fun ThreadSummaryDto.toDomain(): ThreadSummary = ThreadSummary(
    id = id,
    sceneId = sceneId,
    preview = preview,
    lastAt = lastAt,
    turnCount = turnCount,
    unread = unread,
    gradingStatus = gradingStatus
)

fun ThreadMessageDto.toDomain(): ChatMessage = ChatMessage(
    id = id,
    kind = kind,
    roleId = roleId,
    text = text,
    textCn = textCn,
    audioUrl = audioUrl,
    audioMs = audioMs,
    audioPending = audioPending,
    spoke = spoke,
    recognizedText = recognizedText,
    localRecording = localRecording,
    grade = grade?.toDomain()
)

fun ThreadGradeDto.toDomain(): ChatGrade = ChatGrade(
    status = status,
    score = score,
    axes = axes,
    comment = comment,
    commentCn = commentCn
)
