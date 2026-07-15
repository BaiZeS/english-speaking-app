package com.app.english.data.local

import android.content.Context
import android.content.SharedPreferences
import androidx.core.content.edit
import com.app.english.BuildConfig
import dagger.hilt.android.qualifiers.ApplicationContext
import java.util.UUID
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Persistent per-install settings: stable device id (used as `device_id` for
 * /history), backend base URL override, and preferred TTS voice.
 */
@Singleton
class SettingsStore @Inject constructor(@ApplicationContext private val context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    val deviceId: String by lazy { ensureDeviceId() }

    fun getBaseUrl(): String =
        normalizeBaseUrl(prefs.getString(KEY_BASE_URL, null) ?: BuildConfig.BACKEND_BASE_URL)

    fun setBaseUrl(url: String) {
        prefs.edit { putString(KEY_BASE_URL, normalizeBaseUrl(url)) }
    }

    fun getVoice(): String = prefs.getString(KEY_VOICE, DEFAULT_VOICE) ?: DEFAULT_VOICE

    fun setVoice(voice: String) {
        prefs.edit { putString(KEY_VOICE, voice) }
    }

    private fun ensureDeviceId(): String {
        prefs.getString(KEY_DEVICE_ID, null)?.let { return it }
        val id = UUID.randomUUID().toString()
        prefs.edit { putString(KEY_DEVICE_ID, id) }
        return id
    }

    private fun normalizeBaseUrl(url: String): String = if (url.endsWith("/")) url else "$url/"

    companion object {
        private const val PREFS_NAME = "english_assistant_prefs"
        private const val KEY_DEVICE_ID = "device_id"
        private const val KEY_BASE_URL = "base_url"
        private const val KEY_VOICE = "voice"

        // Xunfei Spark super-natural TTS, US English female (x5_EnUs_Grant_flow).
        private const val DEFAULT_VOICE = "x5_EnUs_Grant_flow"
    }
}
