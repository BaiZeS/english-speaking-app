package com.app.english.update

import android.content.Context
import android.content.Intent
import android.net.Uri
import androidx.core.content.FileProvider
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Build the system APK-install intent for a previously downloaded APK file.
 *
 * Android N+ requires ``content://`` URIs through a FileProvider to start the
 * installer, so we never pass plain ``file://`` URIs here. ``addFlags(NEW_TASK)``
 * lets us launch the intent from an Application context (we don't always have
 * an Activity at hand when the download finishes).
 */
@Singleton
class ApkInstaller @Inject constructor(@ApplicationContext private val context: Context) {
    fun buildInstallIntent(apkPath: String): Intent? {
        val file = File(apkPath)
        if (!file.exists() || file.length() <= 0L) return null
        val authority = "${context.packageName}.fileprovider"
        val uri: Uri = try {
            FileProvider.getUriForFile(context, authority, file)
        } catch (e: IllegalArgumentException) {
            // FileProvider not configured for this path (e.g. user wiped app
            // data after we wrote the file). Surface a clear error rather than
            // letting the SecurityException bubble up to the UI.
            return null
        }
        return Intent(Intent.ACTION_INSTALL_PACKAGE).apply {
            setDataAndType(uri, "application/vnd.android.package-archive")
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
        }
    }

    /** Whether the user has already granted the system-level "install unknown apps" right. */
    fun canRequestInstallPackages(): Boolean {
        // Avoid hard-coding Build.VERSION.SDK_INT >= O here to keep the API surface
        // consistent across the support-library versions; the package installer
        // activity will display a clear error if the right is missing.
        return context.packageManager.canRequestPackageInstalls()
    }
}
