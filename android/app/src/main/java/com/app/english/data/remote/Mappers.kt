package com.app.english.data.remote

import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.SceneRole

fun TtsResponseDto.toDomain(): com.app.english.domain.model.TtsAudio =
    com.app.english.domain.model.TtsAudio(
        audioUrl = audioUrl,
        durationMs = durationMs,
        source = source
    )

fun LlmModelDto.toDomain(): com.app.english.domain.model.LlmModel =
    com.app.english.domain.model.LlmModel(
        id = id,
        displayName = displayName,
        provider = provider,
        description = description
    )

fun AppVersionResponseDto.toDomain(): com.app.english.domain.model.AppVersion =
    com.app.english.domain.model.AppVersion(
        latestVersion = latestVersion,
        minSupportedVersion = minSupportedVersion,
        apkUrl = apkUrl,
        releaseNotes = releaseNotes,
        forceUpdate = forceUpdate
    )

fun DialogueSceneDto.toDomain(): DialogueScene = DialogueScene(
    id = id,
    title = title,
    description = description,
    titleEn = titleEn,
    descriptionEn = descriptionEn,
    kind = kind,
    roles = roles.map { it.toDomain() },
    userRole = userRole
)

fun SceneRoleDto.toDomain(): SceneRole = SceneRole(
    id = roleId,
    name = name,
    nameEn = nameEn,
    voice = voice
)
