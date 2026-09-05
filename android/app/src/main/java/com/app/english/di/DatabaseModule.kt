package com.app.english.di

import android.content.Context
import androidx.room.Room
import com.app.english.data.local.AppDatabase
import com.app.english.data.local.CourseCacheDao
import com.app.english.data.local.EnglishContentDatabase
import com.app.english.data.local.ExpressionCacheDao
import com.app.english.data.local.MistakeWordDao
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

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

    /**
     * v2.0 P6 的内容缓存库(计划 §6.5): 与 AppDatabase 完全独立 —— 课本链路的
     * 库 schema 冻结在 v3, 生成课/表达库缓存炸了可以随时重建。
     */
    @Provides
    @Singleton
    fun provideEnglishContentDatabase(
        @ApplicationContext context: Context
    ): EnglishContentDatabase = Room.databaseBuilder(
        context.applicationContext,
        EnglishContentDatabase::class.java,
        "english_content.db"
    ).fallbackToDestructiveMigration().build()

    @Provides
    fun provideMistakeWordDao(db: AppDatabase): MistakeWordDao = db.mistakeWordDao()

    @Provides
    fun provideCourseCacheDao(db: EnglishContentDatabase): CourseCacheDao = db.courseCacheDao()

    @Provides
    fun provideExpressionCacheDao(db: EnglishContentDatabase): ExpressionCacheDao =
        db.expressionCacheDao()
}
