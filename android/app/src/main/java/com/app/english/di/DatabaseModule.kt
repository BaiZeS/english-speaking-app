package com.app.english.di

import android.content.Context
import androidx.room.Room
import com.app.english.data.local.AppDatabase
import com.app.english.data.local.HistoryCacheDao
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

    @Provides
    fun provideHistoryCacheDao(db: AppDatabase): HistoryCacheDao = db.historyCacheDao()
}
