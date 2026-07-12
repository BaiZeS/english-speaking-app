package com.app.english.data.repository

import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.ScoreRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.LessonSummary
import com.app.english.domain.model.ScoreResult
import javax.inject.Inject
import javax.inject.Singleton

interface EnglishRepository {
    suspend fun listLessons(book: String): List<LessonSummary>
    suspend fun getLessonRoles(lessonId: Int, book: String): LessonDetail
    suspend fun getTtsAudioUrl(text: String, voice: String): String
    suspend fun score(
        lessonId: Int,
        lineId: String,
        refText: String,
        audioBase64: String,
        mode: String = "k12"
    ): ScoreResult
}

@Singleton
class EnglishRepositoryImpl @Inject constructor(private val api: EnglishApi) : EnglishRepository {
    override suspend fun listLessons(book: String): List<LessonSummary> =
        api.listLessons(book).map { it.toDomain() }

    override suspend fun getLessonRoles(lessonId: Int, book: String): LessonDetail =
        api.getLessonRoles(lessonId, book).toDomain()

    override suspend fun getTtsAudioUrl(text: String, voice: String): String =
        api.getTts(text, voice).audioUrl

    override suspend fun score(
        lessonId: Int,
        lineId: String,
        refText: String,
        audioBase64: String,
        mode: String
    ): ScoreResult {
        val request = ScoreRequestDto(
            lessonId = lessonId,
            lineId = lineId,
            refText = refText,
            mode = mode,
            audio = audioBase64
        )
        return api.score(request).toDomain()
    }
}
