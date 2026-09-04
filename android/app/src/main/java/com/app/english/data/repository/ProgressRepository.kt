package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 通关进度读路径(计划 §5.2 M3 `course_progress` 物化直读)。
 * 画廊的 cleared/best_total 已由 `GET /scenes` 合并进摘要; 这里给「继续学习」
 * 与未来的我的课程页按 scene 维度取整行。
 */
interface ProgressRepository {
    /** scene_id -> 进度行; 没玩过的课不在表里。 */
    suspend fun listProgress(): Map<String, CourseProgressEntry>
}

/** 一门课的通关现状(`ProgressItem`)。 */
data class CourseProgressEntry(
    val sceneId: String,
    val attempts: Int,
    val cleared: Boolean,
    val bestTotal: Double,
    val lastStage: String,
    val lastSessionId: String,
    val estimatedSeconds: Double
)

@Singleton
class ProgressRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : ProgressRepository {
    override suspend fun listProgress(): Map<String, CourseProgressEntry> =
        api.listCourseProgress(settingsStore.deviceId).progress.associate {
            it.sceneId to CourseProgressEntry(
                sceneId = it.sceneId,
                attempts = it.attempts,
                cleared = it.cleared,
                bestTotal = it.bestTotal,
                lastStage = it.lastStage,
                lastSessionId = it.lastSessionId,
                estimatedSeconds = it.estimatedSeconds
            )
        }
}
