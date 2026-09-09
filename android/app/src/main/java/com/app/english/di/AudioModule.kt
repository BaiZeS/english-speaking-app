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
    @Singleton
    fun provideAudioRecorder(@ApplicationContext context: Context): AudioRecorder =
        AudioRecorder(context)

    // TODO(audio): same scoping bug as provideAudioRecorder had — each injected
    // AudioPlayer is a fresh instance. Left as-is; not on the recording path.
    @Provides
    fun provideAudioPlayer(@ApplicationContext context: Context): AudioPlayer = AudioPlayer(context)
}
