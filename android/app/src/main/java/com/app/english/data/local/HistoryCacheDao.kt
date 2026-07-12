package com.app.english.data.local

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query

@Dao
interface HistoryCacheDao {
    @Query("SELECT * FROM history_cache ORDER BY createdAt DESC LIMIT :limit")
    suspend fun getAll(limit: Int = 50): List<HistoryCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(items: List<HistoryCacheEntity>)

    @Query("DELETE FROM history_cache")
    suspend fun clear()
}
