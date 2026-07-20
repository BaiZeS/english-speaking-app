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
class BooksRepositoryImpl @Inject constructor(private val api: EnglishApi) : BooksRepository {
    override suspend fun listBooks(): List<Book> = api.listBooks().books.map { it.toDomain() }

    override suspend fun listDialogueScenes(): List<DialogueScene> =
        api.listDialogueScenes().scenes.map { it.toDomain() }
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
