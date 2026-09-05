package com.app.english.data.local

import androidx.room.Database
import androidx.room.RoomDatabase

@Database(
    // history_cache 自 v2.0 起**彻底闲置** (DAO/读写路径已全部删除, 全库 grep
    // 零引用)。实体仍留在 entities 里是**故意的**: Room 2.6.1 的 schema 身份
    // 哈希在 version 不变时一改就崩存量安装 (RoomOpenHelper.checkIdentity 无条件
    // throw, fallbackToDestructiveMigration 不覆盖该路径), 而 "AppDatabase 冻结
    // 在 v3 + mistake_words 数据完好" 是升级硬约束 —— 表体因此冻结, 不再有任何
    // 代码路径读写它。
    entities = [HistoryCacheEntity::class, MistakeWordEntity::class],
    // Bumped 2 -> 3 for the mistake_words table. Built with
    // fallbackToDestructiveMigration(): the cache is wiped on upgrade by
    // design (server Postgres is authoritative).
    version = 3,
    exportSchema = false
)
abstract class AppDatabase : RoomDatabase() {
    abstract fun mistakeWordDao(): MistakeWordDao
}
