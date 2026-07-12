package com.app.english.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "history_cache")
data class HistoryCacheEntity(
    @PrimaryKey val id: String,
    val lessonId: Int,
    val lineId: String,
    val scoreTotal: Double,
    val scorePronunciation: Double,
    val scoreFluency: Double,
    val scoreCompleteness: Double,
    val createdAt: String
)
