package com.app.english.update

import com.app.english.domain.model.AppVersion

/** State of an update-check attempt. Pure UI model, no I/O. */
sealed interface UpdateCheckState {
    data object Idle : UpdateCheckState
    data object Checking : UpdateCheckState
    data class UpToDate(val current: String) : UpdateCheckState
    data class UpdateAvailable(val info: UpdateInfo) : UpdateCheckState
    data class Failed(val message: String) : UpdateCheckState
}

/** Everything the UI needs to render the update prompt and download button. */
data class UpdateInfo(
    val currentVersion: String,
    val latestVersion: String,
    val minSupportedVersion: String,
    val apkUrl: String,
    val releaseNotes: String,
    val forceUpdate: Boolean
) {
    companion object {
        fun fromDomain(current: String, version: AppVersion): UpdateInfo = UpdateInfo(
            currentVersion = current,
            latestVersion = version.latestVersion,
            minSupportedVersion = version.minSupportedVersion,
            apkUrl = version.apkUrl,
            releaseNotes = version.releaseNotes,
            forceUpdate = version.forceUpdate
        )
    }
}

/** Lifecycle of an APK download. The UI uses it to show progress and final actions. */
sealed interface DownloadState {
    data object Idle : DownloadState
    data class Downloading(val progress: Int) : DownloadState
    data class Downloaded(val apkPath: String) : DownloadState
    data class Failed(val message: String) : DownloadState
}
