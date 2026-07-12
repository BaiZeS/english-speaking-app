package com.app.english.data.remote

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface EnglishApi {
    @GET("lessons")
    suspend fun listLessons(@Query("book") book: String): List<LessonSummaryDto>

    @GET("lessons/{lessonId}/roles")
    suspend fun getLessonRoles(
        @Path("lessonId") lessonId: Int,
        @Query("book") book: String
    ): LessonDetailDto

    @GET("tts")
    suspend fun getTts(
        @Query("text") text: String,
        @Query("voice") voice: String = "k12_female"
    ): TtsResponseDto

    @POST("score")
    suspend fun score(@Body request: ScoreRequestDto): ScoreResponseDto

    @POST("history")
    suspend fun writeHistory(@Body request: HistoryWriteRequestDto): HistoryItemDto

    @GET("history")
    suspend fun listHistory(
        @Query("device_id") deviceId: String,
        @Query("limit") limit: Int = 50
    ): List<HistoryItemDto>
}
