package com.app.english.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [HistoryCacheEntity::class],
    version = 1,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun historyCacheDao(): HistoryCacheDao
}
