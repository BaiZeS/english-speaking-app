package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.Book
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.PracticeStats
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Read-side repositories for the catalogs + stats endpoints.
 *
 * Kept separate from [EnglishRepository] so we can swap implementations (e.g. an
 * offline cache for [Book]s) without bloating the practice-flow interface.
 */
interface BooksRepository {
    suspend fun listBooks(): List<Book>
    suspend fun listDialogueScenes(): List<DialogueScene>
}

@Singleton
class BooksRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : BooksRepository {
    override suspend fun listBooks(): List<Book> = api.listBooks().books.map { it.toDomain() }

    /**
     * 场景目录**带身份**(§3 C3b): 不带身份只看见内置目录, 自己描的场景永远不出现 ——
     * 这就是"作业 ready 之后刷新一次列表"能看见新场景的原因。
     */
    override suspend fun listDialogueScenes(): List<DialogueScene> =
        api.listDialogueScenes(settingsStore.deviceId).scenes.map { it.toDomain() }
}

interface StatsRepository {
    suspend fun getStats(): PracticeStats
}

@Singleton
class StatsRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : StatsRepository {
    override suspend fun getStats(): PracticeStats = api.getStats(settingsStore.deviceId).toDomain()
}
