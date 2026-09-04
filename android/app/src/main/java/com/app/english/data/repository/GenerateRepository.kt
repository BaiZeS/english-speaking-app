package com.app.english.data.repository

import com.app.english.data.local.CourseCacheDao
import com.app.english.data.local.CourseCacheEntity
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.GenerateSceneRequestDto
import com.app.english.data.remote.SceneCourseDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.GenerationJob
import com.app.english.domain.model.SceneCourseDetail
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json

/**
 * 课程生成链路(计划 §5.3): 一句目标 -> 202 + job_id -> 轮询 jobs -> ready。
 *
 * 生成课就绪时把整课 JSON 快照进 Room `course_cache`(T5 报告: 本机配额下全课
 * 5-10 分钟, 生成一次不容易), 详情页断网时可以从缓存回落。
 */
interface GenerateRepository {
    suspend fun startGeneration(goalText: String): String

    suspend fun pollJob(jobId: String): GenerationJob

    /** 详情读路径: 网络优先, 失败回落 course_cache 快照(没有缓存则原样抛)。 */
    suspend fun getScene(sceneId: String): SceneCourseDetail

    /** 删除自己的生成课并清本地快照。 */
    suspend fun deleteScene(sceneId: String)
}

@Singleton
class GenerateRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore,
    private val courseCacheDao: CourseCacheDao,
    private val json: Json
) : GenerateRepository {

    override suspend fun startGeneration(goalText: String): String = api.generateScene(
        GenerateSceneRequestDto(deviceId = settingsStore.deviceId, goalText = goalText)
    ).jobId

    override suspend fun pollJob(jobId: String): GenerationJob =
        api.getGenerationJob(jobId, settingsStore.deviceId).toDomain()

    override suspend fun getScene(sceneId: String): SceneCourseDetail = try {
        api.getScene(sceneId, settingsStore.deviceId).also { cacheDto(sceneId, it) }.toDomain()
    } catch (e: Exception) {
        val cached = courseCacheDao.get(sceneId) ?: throw e
        json.decodeFromString<SceneCourseDto>(cached.docJson).toDomain()
    }

    private suspend fun cacheDto(sceneId: String, dto: SceneCourseDto) {
        courseCacheDao.put(
            CourseCacheEntity(
                sceneId = sceneId,
                docJson = json.encodeToString(dto),
                savedAtMillis = System.currentTimeMillis()
            )
        )
    }

    override suspend fun deleteScene(sceneId: String) {
        api.deleteScene(sceneId, settingsStore.deviceId)
        courseCacheDao.delete(sceneId)
    }
}
