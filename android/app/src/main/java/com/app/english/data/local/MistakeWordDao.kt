package com.app.english.data.local

import androidx.room.Dao
import androidx.room.Query
import androidx.room.Upsert

@Dao
interface MistakeWordDao {
    @Upsert
    suspend fun insert(word: MistakeWordEntity)

    @Query("DELETE FROM mistake_words WHERE word = :word")
    suspend fun delete(word: String)

    @Query("SELECT * FROM mistake_words WHERE word = :word")
    suspend fun get(word: String): MistakeWordEntity?

    /** Worst-scoring words first. */
    @Query("SELECT * FROM mistake_words ORDER BY lastScore ASC")
    suspend fun all(): List<MistakeWordEntity>
}
