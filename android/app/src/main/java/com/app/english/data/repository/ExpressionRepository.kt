package com.app.english.data.repository

import com.app.english.data.local.ExpressionCacheDao
import com.app.english.data.local.ExpressionCacheEntity
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.CreateExpressionRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.ExpressionEntry
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 个人表达库(计划 §5.7): 润色出来的好说法收藏/去重/删除。
 *
 * Room `expressions_cache` 是离线快照: 每次成功拉列表都整体重写, 网络挂了回落
 * 最近一次成功的列表 —— 表达库是低频读、弱一致就够的场景。
 */
interface ExpressionRepository {
    /** 全量列表(新的在前); 网络失败回落缓存, 连缓存都没有才抛。 */
    suspend fun list(): List<ExpressionEntry>

    /** 收藏一条润色句; 返回 (是否新收藏, 归一化命中时的既有条目)。 */
    suspend fun collect(polish: PolishCollectRequest): Pair<Boolean, ExpressionEntry>

    suspend fun delete(id: String)
}

/** 收藏请求的领域形状(后端按 normalized 润色句去重)。 */
data class PolishCollectRequest(
    val polished: String,
    val original: String,
    val explanationCn: String,
    val sourceLabel: String = "mission",
    val sceneId: String = "",
    val sessionId: String = ""
)

@Singleton
class ExpressionRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore,
    private val cacheDao: ExpressionCacheDao
) : ExpressionRepository {

    override suspend fun list(): List<ExpressionEntry> = try {
        val remote = api.listExpressions(settingsStore.deviceId).map { it.toDomain() }
        cacheDao.putAll(
            remote.map {
                ExpressionCacheEntity(
                    id = it.id,
                    polished = it.polished,
                    original = it.original,
                    explanationCn = it.explanationCn,
                    sourceLabel = it.sourceLabel,
                    sceneId = it.sceneId,
                    createdAt = it.createdAt,
                    cachedAtMillis = System.currentTimeMillis()
                )
            }
        )
        remote
    } catch (e: Exception) {
        val cached = cacheDao.getAll()
        if (cached.isEmpty()) throw e
        cached.map { it.toEntry() }
    }

    override suspend fun collect(polish: PolishCollectRequest): Pair<Boolean, ExpressionEntry> {
        val response = api.createExpression(
            CreateExpressionRequestDto(
                deviceId = settingsStore.deviceId,
                polished = polish.polished,
                original = polish.original,
                explanationCn = polish.explanationCn,
                sourceLabel = polish.sourceLabel,
                sceneId = polish.sceneId,
                sessionId = polish.sessionId
            )
        )
        return response.created to response.expression.toDomain()
    }

    override suspend fun delete(id: String) {
        api.deleteExpression(id, settingsStore.deviceId)
    }

    private fun ExpressionCacheEntity.toEntry(): ExpressionEntry = ExpressionEntry(
        id = id,
        polished = polished,
        original = original,
        explanationCn = explanationCn,
        sourceLabel = sourceLabel,
        sceneId = sceneId,
        createdAt = createdAt
    )
}
