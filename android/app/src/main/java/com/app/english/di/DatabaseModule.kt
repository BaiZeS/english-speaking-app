package com.app.english.di

import android.content.Context
import androidx.room.Room
import com.app.english.data.local.AppDatabase
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/**
 * 本机 Room 库。
 *
 * v3.0 之后**没有任何代码路径读写它** (弱词本与练习记录都随各自功能退役了), 但库本身
 * 必须原样留着: `AppDatabase` 的实体列表与 version 一字不许动 —— Room 2.6.1 的 schema
 * 身份哈希在 version 不变时一改就崩存量安装, 而 v2.3.1 换证书已经让存量设备付出过一次
 * 卸载重装的代价, 不该再来一次。详见 `data/local/AppDatabase.kt` 顶部那段注记。
 */
@Module
@InstallIn(SingletonComponent::class)
object DatabaseModule {
    @Provides
    @Singleton
    fun provideAppDatabase(@ApplicationContext context: Context): AppDatabase =
        Room.databaseBuilder(
            context.applicationContext,
            AppDatabase::class.java,
            "english_assistant.db"
        ).fallbackToDestructiveMigration().build()
}
