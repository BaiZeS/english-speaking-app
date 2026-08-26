package com.app.english.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    entities = [HistoryCacheEntity::class, MistakeWordEntity::class],
    // Bumped 2 -> 3 for the mistake_words table. Built with
    // fallbackToDestructiveMigration(): the cache is wiped on upgrade by
    // design (server Postgres is authoritative).
    version = 3,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun historyCacheDao(): HistoryCacheDao
    abstract fun mistakeWordDao(): MistakeWordDao
}
