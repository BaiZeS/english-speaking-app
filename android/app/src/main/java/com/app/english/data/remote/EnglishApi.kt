package com.app.english.data.remote

import retrofit2.http.Body
import retrofit2.http.DELETE
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
        @Query("voice") voice: String = "Mia"
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
        @Query("book") book: String,
        @Query("device_id") deviceId: String
    ): LessonProgressDto

    @GET("stats")
    suspend fun getStats(@Query("device_id") deviceId: String): StatsResponseDto

    @GET("history")
    suspend fun listHistory(
        @Query("device_id") deviceId: String,
        @Query("limit") limit: Int = 50
    ): List<HistoryItemDto>

    /**
     * 情景课画廊(计划 §5.3)。`category` 为 null 时 Retrofit 会省略该 query,
     * 后端返回全部四类的合并列表; `categories` 计数恒为全量, 不受筛选影响。
     */
    @GET("scenes")
    suspend fun listScenes(
        @Query("category") category: String? = null,
        @Query("device_id") deviceId: String
    ): ScenesResponseDto

    // ====== 情景课全流程(计划 §5.3, P6 消费) ======

    /** 一门课的完整内容(生成课仅归属者可见; 不带身份只看 curated)。 */
    @GET("scenes/{sceneId}")
    suspend fun getScene(
        @Path("sceneId") sceneId: String,
        @Query("device_id") deviceId: String
    ): SceneCourseDto

    /** 删除自己的生成课(curated 405)。 */
    @DELETE("scenes/{sceneId}")
    suspend fun deleteScene(@Path("sceneId") sceneId: String, @Query("device_id") deviceId: String)

    @POST("scenes/generate")
    suspend fun generateScene(@Body request: GenerateSceneRequestDto): GenerateAcceptedDto

    @GET("scenes/jobs/{jobId}")
    suspend fun getGenerationJob(
        @Path("jobId") jobId: String,
        @Query("device_id") deviceId: String
    ): GenerationJobDto

    @GET("courses/progress")
    suspend fun listCourseProgress(@Query("device_id") deviceId: String): CourseProgressPageDto

    // ====== 通关会话状态机 ======

    @POST("sessions")
    suspend fun createSession(@Body request: CreateSessionRequestDto): SessionViewDto

    /** 最近会话列表; `status=active` 过滤未打完的场(首页「继续学习」)。 */
    @GET("sessions")
    suspend fun listSessions(
        @Query("device_id") deviceId: String,
        @Query("status") status: String = "",
        @Query("limit") limit: Int = 10
    ): List<SessionSummaryDto>

    /** 崩溃恢复快照(stage/mission/review 视图 + 整课内容)。 */
    @GET("sessions/{sessionId}")
    suspend fun getSession(
        @Path("sessionId") sessionId: String,
        @Query("device_id") deviceId: String
    ): SessionViewDto

    @POST("sessions/{sessionId}/step")
    suspend fun submitStep(
        @Path("sessionId") sessionId: String,
        @Body request: StepAttemptRequestDto
    ): StepAttemptResponseDto

    @POST("sessions/{sessionId}/skip-step")
    suspend fun skipStep(
        @Path("sessionId") sessionId: String,
        @Body request: StepAttemptRequestDto
    ): StepAttemptResponseDto

    @POST("sessions/{sessionId}/mission")
    suspend fun submitMissionTurn(
        @Path("sessionId") sessionId: String,
        @Body request: MissionTurnRequestDto
    ): MissionTurnResponseDto

    @POST("sessions/{sessionId}/hint")
    suspend fun requestHint(
        @Path("sessionId") sessionId: String,
        @Body request: MissionTurnRequestDto
    ): HintResponseDto

    @POST("sessions/{sessionId}/finish-mission")
    suspend fun finishMission(
        @Path("sessionId") sessionId: String,
        @Body request: MissionTurnRequestDto
    ): FinishMissionResponseDto

    // ====== CEFR 测评(计划 §5.3, P7 消费) ======

    /** 题库摘要(题目本体 + 建议用时; 参考要点永不下发)。 */
    @GET("assessment")
    suspend fun getAssessmentBank(): AssessmentBankDto

    @POST("assessment/start")
    suspend fun startAssessment(
        @Body request: AssessmentStartRequestDto
    ): AssessmentStartResponseDto

    /** 音频转写不出(讯飞未配)时后端 400 TRANSCRIPT_UNAVAILABLE —— 引导改文本。 */
    @POST("assessment/{attemptId}/answer")
    suspend fun submitAssessmentAnswer(
        @Path("attemptId") attemptId: String,
        @Body request: AssessmentAnswerRequestDto
    ): AssessmentAnswerResponseDto

    /** 一次批量 LLM 判级; 幂等(已完成重放同形状)。 */
    @POST("assessment/{attemptId}/complete")
    suspend fun completeAssessment(
        @Path("attemptId") attemptId: String,
        @Body request: AssessmentCompleteRequestDto
    ): AssessmentCompleteResponseDto

    // ====== 能力画像(§5.6; days 只接受 7/30/90) ======

    @GET("ability")
    suspend fun getAbility(
        @Query("device_id") deviceId: String,
        @Query("days") days: Int = 30
    ): AbilityResponseDto

    // ====== 独立润色(§5.7) ======

    @POST("polish")
    suspend fun polishText(@Body request: PolishRequestDto): PolishResponseDto

    // ====== 个人表达库(§5.7) ======

    @GET("expressions")
    suspend fun listExpressions(@Query("device_id") deviceId: String): List<ExpressionDto>

    @POST("expressions")
    suspend fun createExpression(
        @Body request: CreateExpressionRequestDto
    ): CreateExpressionResponseDto

    @DELETE("expressions/{id}")
    suspend fun deleteExpression(@Path("id") id: String, @Query("device_id") deviceId: String)
}
