package com.app.english.di

import com.app.english.data.repository.ChatRepository
import com.app.english.data.repository.ChatRepositoryImpl
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.EnglishRepositoryImpl
import com.app.english.data.repository.GenerateRepository
import com.app.english.data.repository.GenerateRepositoryImpl
import dagger.Binds
import dagger.Module
import dagger.hilt.InstallIn
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

/** v3.0 只剩情景对话一条线: 线程数据面 + 目录/TTS/翻译/版本 + 自定义场景生成。 */
@Module
@InstallIn(SingletonComponent::class)
abstract class RepositoryModule {
    @Binds
    @Singleton
    abstract fun bindEnglishRepository(impl: EnglishRepositoryImpl): EnglishRepository

    @Binds
    @Singleton
    abstract fun bindChatRepository(impl: ChatRepositoryImpl): ChatRepository

    @Binds
    @Singleton
    abstract fun bindGenerateRepository(impl: GenerateRepositoryImpl): GenerateRepository
}
