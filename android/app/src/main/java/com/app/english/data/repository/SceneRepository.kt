package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.SceneCatalog
import com.app.english.domain.model.SceneSummary
import java.util.concurrent.ConcurrentHashMap
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 情景课画廊读路径(计划 §6.5)。
 *
 * 与 [BooksRepository] 一样是「只读目录」类仓库: 失败时把异常抛给 ViewModel,
 * 由界面层的 `ErrorState` 统一呈现 —— 不在这里吞掉错误, 也不返回空列表假装成功。
 *
 * 缓存是进程内的(按 category 分 key, 含 null=全部): 画廊是可重复访问的 Tab,
 * 每次切换都重新拉一遍没必要。后端 curated 内容本身有 60s TTL, 这里取同样的窗口。
 */
interface SceneRepository {
    /** @param category null / 空白 = 全部分类。 @param refresh true 时跳过新鲜缓存。 */
    suspend fun listScenes(category: String? = null, refresh: Boolean = false): SceneCatalog

    /** 丢弃全部缓存(生成课保存成功后、或调试用的手动刷新)。 */
    fun invalidate()
}

@Singleton
class SceneRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : SceneRepository {
    private data class CachedPage(val catalog: SceneCatalog, val fetchedAtMillis: Long) {
        fun isFresh(now: Long): Boolean = now - fetchedAtMillis < CACHE_TTL_MILLIS
    }

    private val cache = ConcurrentHashMap<String, CachedPage>()

    override suspend fun listScenes(category: String?, refresh: Boolean): SceneCatalog {
        val key = cacheKey(category)
        val now = System.currentTimeMillis()
        if (!refresh) {
            cache[key]?.takeIf { it.isFresh(now) }?.let { return it.catalog }
        }
        val remote = try {
            api.listScenes(category?.trim()?.takeIf { it.isNotEmpty() }, settingsStore.deviceId)
                .toDomain()
        } catch (e: Exception) {
            // 网络失败但有(哪怕过期的)缓存 -> 用缓存兜底; 否则原样抛出交给 ErrorState。
            val cached = cache[key]?.catalog
            if (cached != null) cached else throw e
        }
        cache[key] = CachedPage(remote, now)
        return remote
    }

    override fun invalidate() = cache.clear()

    private fun cacheKey(category: String?): String =
        category?.trim()?.lowercase()?.takeIf { it.isNotEmpty() } ?: KEY_ALL

    private companion object {
        const val KEY_ALL = "*"
        const val CACHE_TTL_MILLIS = 60_000L
    }
}

/**
 * 「今日推荐」(计划 §6.3, P7 起接真逻辑): 画像最低维 -> 场景 `skills` 匹配。
 *
 * 兜底链: 画像为空/没有最低维(stub、什么都没练)→ curated 第 1 课;
 * 最低维没有任何场景带这个 skill → curated 第 1 课; 连 curated 都没有 → 全表
 * 第一门。**冷启动永远有推荐, 但绝不假装知道你弱在哪。**
 */
fun List<SceneSummary>.pickTodayScene(weakestDimension: String?): SceneSummary? {
    if (isEmpty()) return null
    if (weakestDimension != null) {
        firstOrNull { weakestDimension in it.skills }?.let { return it }
    }
    return firstOrNull { it.source == "curated" } ?: first()
}
