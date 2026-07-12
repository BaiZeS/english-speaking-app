package com.app.english.di

import android.content.Context
import com.app.english.audio.AudioEncoder
import com.app.english.audio.AudioPlayer
import com.app.english.audio.AudioRecorder
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
object AudioModule {
    @Provides
    @Singleton
    fun provideAudioEncoder(): AudioEncoder = AudioEncoder()

    @Provides
    fun provideAudioRecorder(@ApplicationContext context: Context): AudioRecorder =
        AudioRecorder(context)

    @Provides
    fun provideAudioPlayer(@ApplicationContext context: Context): AudioPlayer = AudioPlayer(context)
}
