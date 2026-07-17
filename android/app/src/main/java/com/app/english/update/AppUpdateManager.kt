package com.app.english.update

import android.content.Context
import com.app.english.BuildConfig
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import dagger.hilt.android.qualifiers.ApplicationContext
import javax.inject.Inject
import javax.inject.Singleton
import timber.log.Timber

/**
 * Decide whether the running app should prompt for an update.
 *
 * Wraps the backend call so the UI can stay state-driven and so we have a single
 * place to suppress prompts the user already dismissed (via [SettingsStore]).
 */
@Singleton
class AppUpdateManager @Inject constructor(
    @ApplicationContext private val context: Context,
    private val repository: EnglishRepository,
    private val settingsStore: SettingsStore
) {
    /** The version string baked into the APK at build time. */
    val currentVersion: String = BuildConfig.VERSION_NAME

    /**
     * Fetch the backend's advertised version and compare it to the running build.
     *
     * Returns:
     *  - [UpdateCheckState.UpToDate] when current >= latest
     *  - [UpdateCheckState.UpdateAvailable] when latest > current (respecting
     *    the user's "skip this version" preference unless [force] is true or
     *    the running build is below the minimum supported version)
     *  - [UpdateCheckState.Failed] for any error
     */
    suspend fun checkForUpdate(force: Boolean = false): UpdateCheckState {
        val current = currentVersion
        return try {
            val remote = repository.getAppVersion()
            val latest = remote.latestVersion
            if (SemVer.isOlder(current, remote.minSupportedVersion)) {
                // The server marked the running build as unsupported: always
                // prompt, even if the user previously dismissed this version.
                UpdateCheckState.UpdateAvailable(UpdateInfo.fromDomain(current, remote))
            } else if (SemVer.isNewer(latest, current)) {
                val dismissed = settingsStore.getDismissedUpdateVersion()
                if (!force && dismissed == latest) {
                    UpdateCheckState.UpToDate(current)
                } else {
                    UpdateCheckState.UpdateAvailable(UpdateInfo.fromDomain(current, remote))
                }
            } else {
                UpdateCheckState.UpToDate(current)
            }
        } catch (e: Exception) {
            Timber.w(e, "Update check failed")
            UpdateCheckState.Failed(e.message ?: "无法连接到更新服务")
        }
    }

    fun markVersionDismissed(version: String) {
        settingsStore.setDismissedUpdateVersion(version)
    }
}
