package com.app.english.data.repository

import com.app.english.data.local.MistakeWordDao
import com.app.english.data.local.MistakeWordEntity
import com.app.english.domain.model.ScoreResult
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Local ledger of weak/mistake words for the drill screen. Backed by Room
 * (cache-level data; server Postgres stays authoritative for history, so
 * destructive migrations are acceptable by design).
 */
interface MistakeWordRepository {
    suspend fun collectFromResult(book: String, lessonId: Int, lineId: String, result: ScoreResult)

    suspend fun list(): List<MistakeWordEntity>

    suspend fun graduate(word: String)
}

@Singleton
class MistakeWordRepositoryImpl @Inject constructor(private val dao: MistakeWordDao) :
    MistakeWordRepository {
    override suspend fun collectFromResult(
        book: String,
        lessonId: Int,
        lineId: String,
        result: ScoreResult
    ) {
        val now = System.currentTimeMillis()
        result.wordDetails
            .filter { it.word.isNotBlank() && it.score < WEAK_WORD_THRESHOLD }
            .forEach { detail ->
                val attempts = (dao.get(detail.word)?.attempts ?: 0) + 1
                dao.insert(
                    MistakeWordEntity(
                        word = detail.word,
                        ipa = detail.ipa,
                        book = book,
                        lessonId = lessonId,
                        lineId = lineId,
                        lastScore = detail.score,
                        attempts = attempts,
                        updatedAt = now
                    )
                )
            }
    }

    override suspend fun list(): List<MistakeWordEntity> = dao.all()

    override suspend fun graduate(word: String) = dao.delete(word)
}

/** Score below which a word is considered weak and collected for drill. */
private const val WEAK_WORD_THRESHOLD = 70.0
