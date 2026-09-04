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
 * 「今日推荐」冷启动用的固定 curated 课 id(计划 §6.3: 冷启动给 curated 第 1 课)。
 *
 * P7 会把这里换成「画像最低维度 × 场景 skills」的匹配; 现在先按 id 命中, 命不中
 * (后端改了内容清单)就退回首门课, 不给空白卡片。
 */
const val RECOMMENDED_SCENE_ID: String = "scene_workplace_project_update"

fun List<SceneSummary>.pickRecommended(preferredId: String = RECOMMENDED_SCENE_ID): SceneSummary? =
    firstOrNull { it.id == preferredId } ?: firstOrNull()
