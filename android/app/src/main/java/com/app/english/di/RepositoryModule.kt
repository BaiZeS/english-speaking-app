package com.app.english.di

import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.EnglishRepositoryImpl
import com.app.english.data.repository.HistoryRepository
import com.app.english.data.repository.HistoryRepositoryImpl
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {
    @Binds
    @Singleton
    abstract fun bindEnglishRepository(impl: EnglishRepositoryImpl): EnglishRepository

    @Binds
    @Singleton
    abstract fun bindHistoryRepository(impl: HistoryRepositoryImpl): HistoryRepository
}
