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
 * Persistent per-install settings:
 *  - stable device id (used as `device_id` for /history)
 *  - backend base URL override
 *  - preferred TTS voice
 *  - selected LLM model id for free dialogue
 *  - selected book id for the lesson list (default = empty = use server default)
 *  - selected dialogue scene id (default = empty = use server default)
 *  - the latest version for which the user dismissed the update prompt
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

    /** Selected LLM model id; `null` means "use backend default". */
    fun getSelectedModelId(): String? =
        prefs.getString(KEY_LLM_MODEL_ID, null)?.takeIf { it.isNotBlank() }

    fun setSelectedModelId(modelId: String?) {
        prefs.edit {
            if (modelId.isNullOrBlank()) {
                remove(
                    KEY_LLM_MODEL_ID
                )
            } else {
                putString(KEY_LLM_MODEL_ID, modelId)
            }
        }
    }

    /** Selected book id; `null` means "let the server pick the default". */
    fun getSelectedBookId(): String? =
        prefs.getString(KEY_BOOK_ID, null)?.takeIf { it.isNotBlank() }

    fun setSelectedBookId(bookId: String?) {
        prefs.edit {
            if (bookId.isNullOrBlank()) remove(KEY_BOOK_ID) else putString(KEY_BOOK_ID, bookId)
        }
    }

    /** Selected dialogue scene id; `null` means "let the server pick the default". */
    fun getSelectedSceneId(): String? =
        prefs.getString(KEY_SCENE_ID, null)?.takeIf { it.isNotBlank() }

    fun setSelectedSceneId(sceneId: String?) {
        prefs.edit {
            if (sceneId.isNullOrBlank()) remove(KEY_SCENE_ID) else putString(KEY_SCENE_ID, sceneId)
        }
    }

    /** Last version string the user acknowledged (dismissed) the update prompt for. */
    fun getDismissedUpdateVersion(): String? =
        prefs.getString(KEY_DISMISSED_UPDATE_VERSION, null)?.takeIf { it.isNotBlank() }

    fun setDismissedUpdateVersion(version: String) {
        prefs.edit { putString(KEY_DISMISSED_UPDATE_VERSION, version) }
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
        private const val KEY_LLM_MODEL_ID = "llm_model_id"
        private const val KEY_BOOK_ID = "book_id"
        private const val KEY_SCENE_ID = "scene_id"
        private const val KEY_DISMISSED_UPDATE_VERSION = "dismissed_update_version"

        // Xunfei Spark super-natural TTS, US English female (x5_EnUs_Grant_flow).
        private const val DEFAULT_VOICE = "x5_EnUs_Grant_flow"
    }
}
