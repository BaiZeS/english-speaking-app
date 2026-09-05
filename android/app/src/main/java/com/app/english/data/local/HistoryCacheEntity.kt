package com.app.english.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

/**
 * **冻结的表壳 (P8 死代码清理)**: v2.0 起全 app 无任何读写路径 (DAO/DI 已删)。
 * 保留注册只为守住 AppDatabase v3 的 schema 身份哈希 —— 移除实体会在无版本
 * 递增时让全部存量安装 open 即崩 (详见 [AppDatabase] 注释)。mistake_words
 * 数据因此完好。
 */
@Entity(tableName = "history_cache")
data class HistoryCacheEntity(
    @PrimaryKey val id: String,
    val book: String = "nce1",
    val lessonId: Int,
    val lineId: String,
    val scoreTotal: Double,
    val scorePronunciation: Double,
    val scoreFluency: Double,
    val scoreCompleteness: Double,
    val createdAt: String
)
