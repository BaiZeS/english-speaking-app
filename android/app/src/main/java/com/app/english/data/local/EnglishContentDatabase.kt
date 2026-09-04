package com.app.english.data.local

import androidx.room.ColumnInfo
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.PrimaryKey
import androidx.room.Query
import androidx.room.RoomDatabase
import kotlinx.coroutines.flow.Flow

/**
 * `EnglishContentDatabase` v1(计划 §6.5): 生成课快照 + 表达库的**离线缓存**,
 * 独立于 AppDatabase v3(课本链路的库冻结不动, 也不碰 mistake_words)。
 *
 * 语义是「快照」而不是真相源: 网络可用时始终以后端为准, 断网/失败时回落到这里
 * 最近一次成功的数据, 让生成课与表达库离线可看。
 */
@Entity(tableName = "course_cache")
data class CourseCacheEntity(
    @PrimaryKey @ColumnInfo(name = "scene_id") val sceneId: String,
    /** 整门课的 `SceneCourseDto` JSON 序列化(kotlinx), 反解即得全部内容。 */
    val docJson: String,
    val savedAtMillis: Long
)

@Entity(tableName = "expressions_cache")
data class ExpressionCacheEntity(
    @PrimaryKey val id: String,
    val polished: String,
    val original: String,
    @ColumnInfo(name = "explanation_cn") val explanationCn: String,
    @ColumnInfo(name = "source_label") val sourceLabel: String,
    @ColumnInfo(name = "scene_id") val sceneId: String,
    @ColumnInfo(name = "created_at") val createdAt: String,
    @ColumnInfo(name = "cached_at_millis") val cachedAtMillis: Long
)

@Dao
interface CourseCacheDao {
    @Query("SELECT * FROM course_cache WHERE scene_id = :sceneId")
    suspend fun get(sceneId: String): CourseCacheEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun put(entity: CourseCacheEntity)

    @Query("DELETE FROM course_cache WHERE scene_id = :sceneId")
    suspend fun delete(sceneId: String)
}

@Dao
interface ExpressionCacheDao {
    @Query("SELECT * FROM expressions_cache ORDER BY created_at DESC")
    fun observeAll(): Flow<List<ExpressionCacheEntity>>

    @Query("SELECT * FROM expressions_cache ORDER BY created_at DESC")
    suspend fun getAll(): List<ExpressionCacheEntity>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun putAll(entities: List<ExpressionCacheEntity>)

    @Query("DELETE FROM expressions_cache")
    suspend fun clear()
}

@Database(
    entities = [CourseCacheEntity::class, ExpressionCacheEntity::class],
    version = 1,
    exportSchema = false
)
abstract class EnglishContentDatabase : RoomDatabase() {
    abstract fun courseCacheDao(): CourseCacheDao

    abstract fun expressionCacheDao(): ExpressionCacheDao
}
