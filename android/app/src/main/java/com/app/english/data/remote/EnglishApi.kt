package com.app.english.data.remote

import retrofit2.http.Body
import retrofit2.http.DELETE
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/**
 * v3.0 之后后端只剩情景对话一条产品线, 这个接口也就只剩它的四面:
 * 场景目录 / 会话线程 / 语音条 / 长按翻译, 加上模型目录与 OTA 版本两个支撑面。
 *
 * 被删的是单词与课程那一整族 (`lessons` `books` `sessions/*` `score` `scenes/{…}`
 * `assessment` `expressions` `stats` `ability` `polish` `history`) —— 对应的功能已从
 * 产品里移除, 不是搬到别处。
 */
interface EnglishApi {

    // ====== 场景目录 ======

    /** 场景目录; 带身份时按归属合并学员自己的自定义场景 (§3 C3b, `kind="custom"`)。 */
    @GET("dialogue/scenes")
    suspend fun listDialogueScenes(@Query("device_id") deviceId: String): DialogueScenesResponseDto

    /**
     * 描一个自定义对话场景 -> **202** `{job_id, polling_url}` (§3 C3)。
     * 作业与已退役的整课生成同居一张表, 所以轮询仍走 [getGenerationJob] (返回的 `kind`
     * 是 `scene_brief`); 就绪后重打一次 [listDialogueScenes] 就能看到新场景。
     */
    @POST("dialogue/scenes/custom")
    suspend fun createCustomScene(@Body request: CustomSceneRequestDto): GenerateAcceptedDto

    /** 生成任务轮询 (自定义场景骨架用)。 */
    @GET("scenes/jobs/{jobId}")
    suspend fun getGenerationJob(
        @Path("jobId") jobId: String,
        @Query("device_id") deviceId: String
    ): GenerationJobDto

    // ====== 会话线程 ======

    /** 会话列表 (微信首页那一列), 最近活跃倒序。 */
    @GET("dialogue/threads")
    suspend fun listThreads(@Query("device_id") deviceId: String): List<ThreadSummaryDto>

    /**
     * 打开一个场景的会话; 已存在则**幂等返回既有那条**。
     * 首次进入把开场白落成语音气泡 (后端请求内合成, 拿不到就是 `audio_pending`)。
     */
    @POST("dialogue/threads")
    suspend fun openThread(
        @Body request: ThreadCreateRequestDto,
        @Query("device_id") deviceId: String
    ): ThreadViewDto

    /** 全量消息 —— 也是评分回填的读取面 (顶层 `grading_status` + 逐颗气泡的 grade)。 */
    @GET("dialogue/threads/{threadId}")
    suspend fun getThread(
        @Path("threadId") threadId: String,
        @Query("device_id") deviceId: String
    ): ThreadViewDto

    @DELETE("dialogue/threads/{threadId}")
    suspend fun deleteThread(
        @Path("threadId") threadId: String,
        @Query("device_id") deviceId: String
    ): ThreadDeletedDto

    /** 提交一轮: 听写 -> 台词 (带语音条) -> 建议回答 -> 评分占位。 */
    @POST("dialogue/threads/{threadId}/turn")
    suspend fun submitTurn(
        @Path("threadId") threadId: String,
        @Body request: ThreadTurnRequestDto,
        @Query("device_id") deviceId: String
    ): ThreadTurnResponseDto

    // ====== 语音条与翻译 ======

    /**
     * 语音条的兜底合成。后端在请求内已经试过一次 (预算 3s), 给不出 URL 时气泡带
     * `audio_pending=true`, 客户端拿这条按需补 —— 所以它**必须**留着。
     */
    @GET("tts")
    suspend fun getTts(
        @Query("text") text: String,
        @Query("voice") voice: String = "Mia"
    ): TtsResponseDto

    /** 长按翻译: 只服务没有现成双语的那条消息。 */
    @POST("translate")
    suspend fun translate(@Body request: TranslateRequestDto): TranslateResponseDto

    // ====== 支撑面 ======

    @GET("llm/models")
    suspend fun listLlmModels(): LlmModelsResponseDto

    @GET("app/version")
    suspend fun getAppVersion(): AppVersionResponseDto
}
