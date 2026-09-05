package com.app.english.data.repository

import com.app.english.data.local.ExpressionCacheDao
import com.app.english.data.local.ExpressionCacheEntity
import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.CreateExpressionRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.PolishRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.ExpressionEntry
import com.app.english.domain.model.PolishOutcome
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

    /** 强制走网络(成功即重写快照); 失败抛给调用方, 由界面层决定降级呈现。 */
    suspend fun refresh(): List<ExpressionEntry>

    /** Room 快照直读(进页先渲染它, 再由 [refresh] 做网络刷新; 没有就返回空)。 */
    suspend fun cached(): List<ExpressionEntry>

    /** 收藏一条润色句; 返回 (是否新收藏, 归一化命中时的既有条目)。 */
    suspend fun collect(polish: PolishCollectRequest): Pair<Boolean, ExpressionEntry>

    /** 对任意一句 POST /polish 并 collect=true 直收入库(§5.7 表达库的「+」入口)。 */
    suspend fun polishAndCollect(text: String, sceneId: String = ""): PolishOutcome

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
        refresh()
    } catch (e: Exception) {
        val cached = cacheDao.getAll()
        if (cached.isEmpty()) throw e
        cached.map { it.toEntry() }
    }

    override suspend fun refresh(): List<ExpressionEntry> {
        val remote = api.listExpressions(settingsStore.deviceId).map { it.toDomain() }
        // 快照 = 服务端全量列表的镜像: 先清空再整表重写,
        // 否则别处删掉的条目会永远赖在离线缓存里(删了又"复活")。
        cacheDao.clear()
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
        return remote
    }

    override suspend fun cached(): List<ExpressionEntry> = cacheDao.getAll().map { it.toEntry() }

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

    override suspend fun polishAndCollect(text: String, sceneId: String): PolishOutcome {
        val outcome = api.polishText(
            PolishRequestDto(
                text = text.trim(),
                deviceId = settingsStore.deviceId,
                collect = true,
                sceneId = sceneId
            )
        ).toDomain()
        // collect=true 直收入了服务端表达库; 本地快照跟着重写一次, 离线也能看到。
        runCatching { list() }
        return outcome
    }

    override suspend fun delete(id: String) {
        api.deleteExpression(id, settingsStore.deviceId)
        // 服务端删成功 = 快照同步剪掉这行; 就算刷新挂了下次进页也能自愈。
        cacheDao.delete(id)
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
