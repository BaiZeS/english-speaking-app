package com.app.english.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * A word the user has scored below the weak-word threshold (70) at least once,
 * driving the mistake-word drill screen. The primary key is the word itself:
 * re-scoring the same weak word updates the row in place (worst-first list).
 */
@Entity(tableName = "mistake_words")
data class MistakeWordEntity(
    @PrimaryKey val word: String,
    val ipa: String?,
    val book: String,
    val lessonId: Int,
    val lineId: String,
    val lastScore: Double,
    val attempts: Int = 0,
    val updatedAt: Long
)
