package com.app.english.di

import com.app.english.data.repository.BooksRepository
import com.app.english.data.repository.BooksRepositoryImpl
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.EnglishRepositoryImpl
import com.app.english.data.repository.HistoryRepository
import com.app.english.data.repository.HistoryRepositoryImpl
import com.app.english.data.repository.StatsRepository
import com.app.english.data.repository.StatsRepositoryImpl
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

    @Binds
    @Singleton
    abstract fun bindBooksRepository(impl: BooksRepositoryImpl): BooksRepository

    @Binds
    @Singleton
    abstract fun bindStatsRepository(impl: StatsRepositoryImpl): StatsRepository
}
