package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.CustomSceneRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.GenerationJob
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 自定义场景的生成链路: 一句话描述 -> 202 + job_id -> 轮询 -> ready。
 *
 * 轮询端点 `GET /scenes/jobs/{jobId}` 与已退役的整课生成共用同一张 job 表, 所以
 * [pollJob] 是**唯一**的轮询通道 —— 别再为自定义场景开第二条。就绪后重打一次
 * 场景目录就能看到新场景 (目录按归属合并 `kind="custom"`)。
 *
 * 整课生成时代的 `course_cache` 本地快照回落已经随课程产品线删除: 生成一门课要
 * 5-10 分钟所以当年值得缓存, 生成一页对话骨架只要几十秒且失败可以重描。
 */
interface GenerateRepository {
    /** 描一个自定义对话场景 -> job id。 */
    suspend fun startCustomScene(sceneBrief: String): String

    suspend fun pollJob(jobId: String): GenerationJob
}

@Singleton
class GenerateRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : GenerateRepository {

    override suspend fun startCustomScene(sceneBrief: String): String = api.createCustomScene(
        CustomSceneRequestDto(sceneBrief = sceneBrief, deviceId = settingsStore.deviceId)
    ).jobId

    override suspend fun pollJob(jobId: String): GenerationJob =
        api.getGenerationJob(jobId, settingsStore.deviceId).toDomain()
}
