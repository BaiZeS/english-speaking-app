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
        @Query("voice") voice: String = "x5_EnUs_Grant_flow"
    ): TtsResponseDto

    @POST("dialogue/generate")
    suspend fun generateDialogue(
        @Body request: DialogueGenerateRequestDto
    ): DialogueGenerateResponseDto

    @POST("dialogue/turn")
    suspend fun dialogueTurn(@Body request: DialogueTurnRequestDto): DialogueTurnResponseDto

    @POST("score")
    suspend fun score(@Body request: ScoreRequestDto): ScoreResponseDto

    @POST("history")
    suspend fun writeHistory(@Body request: HistoryWriteRequestDto): HistoryItemDto

    @GET("llm/models")
    suspend fun listLlmModels(): LlmModelsResponseDto

    @GET("app/version")
    suspend fun getAppVersion(): AppVersionResponseDto

    @GET("books")
    suspend fun listBooks(): BooksResponseDto

    @GET("dialogue/scenes")
    suspend fun listDialogueScenes(): DialogueScenesResponseDto

    @GET("lessons/{lessonId}/progress")
    suspend fun getLessonProgress(
        @Path("lessonId") lessonId: Int,
        @Query("device_id") deviceId: String
    ): LessonProgressDto

    @GET("stats")
    suspend fun getStats(@Query("device_id") deviceId: String): StatsResponseDto

    @GET("history")
    suspend fun listHistory(
        @Query("device_id") deviceId: String,
        @Query("limit") limit: Int = 50
    ): List<HistoryItemDto>
}
