package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.HistoryWriteRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.HistoryItem
import javax.inject.Inject
import javax.inject.Singleton

interface HistoryRepository {
    suspend fun write(
        lessonId: Int,
        lineId: String,
        audioPath: String,
        scoreTotal: Double,
        scorePronunciation: Double,
        scoreFluency: Double,
        scoreCompleteness: Double
    ): HistoryItem

    suspend fun list(limit: Int = 50): List<HistoryItem>
}

@Singleton
class HistoryRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : HistoryRepository {
    override suspend fun write(
        lessonId: Int,
        lineId: String,
        audioPath: String,
        scoreTotal: Double,
        scorePronunciation: Double,
        scoreFluency: Double,
        scoreCompleteness: Double
    ): HistoryItem {
        val request = HistoryWriteRequestDto(
            deviceId = settingsStore.deviceId,
            lessonId = lessonId,
            lineId = lineId,
            audioPath = audioPath,
            scoreTotal = scoreTotal,
            scorePronunciation = scorePronunciation,
            scoreFluency = scoreFluency,
            scoreCompleteness = scoreCompleteness
        )
        return api.writeHistory(request).toDomain()
    }

    override suspend fun list(limit: Int): List<HistoryItem> =
        api.listHistory(settingsStore.deviceId, limit).map { it.toDomain() }
}
