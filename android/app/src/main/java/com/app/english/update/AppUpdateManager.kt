package com.app.english.update

import android.content.Context
import com.app.english.BuildConfig
import com.app.english.data.local.SettingsStore
import com.app.english.data.repository.EnglishRepository
import com.app.english.domain.model.AppVersion
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
            decideUpdate(
                current = current,
                remote = repository.getAppVersion(),
                dismissedVersion = settingsStore.getDismissedUpdateVersion(),
                force = force
            )
        } catch (e: Exception) {
            Timber.w(e, "Update check failed")
            UpdateCheckState.Failed(e.message ?: "无法连接到更新服务")
        }
    }

    fun markVersionDismissed(version: String) {
        settingsStore.setDismissedUpdateVersion(version)
    }
}

/**
 * 更新检查的纯判定核 (P8·2e: 从 [checkForUpdate] 里剥出来, JVM 可测)。
 *
 * 语义与 v2.0 服务端约定锁死: 未显式配置 APP_MIN_SUPPORTED_VERSION 时,
 * 后端回发 ``min_supported_version = "0.0.0"`` 哨兵 + force_update=false ——
 * 任何真实版本都不会落进「不支持」分支, 「稍后再说」(dismissed) 保持有效;
 * 只有运维显式收紧 min 且 current 低于它, 才无视 dismissed 必弹。
 */
internal fun decideUpdate(
    current: String,
    remote: AppVersion,
    dismissedVersion: String?,
    force: Boolean
): UpdateCheckState = when {
    SemVer.isOlder(current, remote.minSupportedVersion) ->
        UpdateCheckState.UpdateAvailable(UpdateInfo.fromDomain(current, remote))
    SemVer.isNewer(remote.latestVersion, current) &&
        (force || dismissedVersion != remote.latestVersion) ->
        UpdateCheckState.UpdateAvailable(UpdateInfo.fromDomain(current, remote))
    else -> UpdateCheckState.UpToDate(current)
}
