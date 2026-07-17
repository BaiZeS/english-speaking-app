package com.app.english

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.ui.navigation.AppNavHost
import com.app.english.ui.theme.EnglishAssistantTheme
import com.app.english.update.ApkInstaller
import com.app.english.update.AppUpdateViewModel
import com.app.english.update.UpdateCheckState
import com.app.english.update.UpdateDialog
import dagger.hilt.android.AndroidEntryPoint
import javax.inject.Inject
import timber.log.Timber

@AndroidEntryPoint
class MainActivity : ComponentActivity() {
    @Inject lateinit var apkInstaller: ApkInstaller

    private val updateViewModel: AppUpdateViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            EnglishAssistantTheme {
                AppNavHost()
                UpdateHost(updateViewModel, apkInstaller)
            }
        }
        // Kick off the update check on cold start. Network failure is silently
        // swallowed by AppUpdateManager; the dialog only appears when there is
        // genuinely a newer version to offer.
        updateViewModel.check()
    }

    override fun onResume() {
        super.onResume()
        // If the user just granted REQUEST_INSTALL_PACKAGES from settings and
        // came back, the system will have already cleared Downloaded. We just
        // re-check in case there's a new release behind the previous gate.
        updateViewModel.check()
    }
}

@Composable
private fun UpdateHost(viewModel: AppUpdateViewModel, installer: ApkInstaller) {
    val checkState by viewModel.checkState.collectAsStateWithLifecycle()
    val downloadState by viewModel.downloadState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    // Reset transient download state when the user backgrounds the dialog so
    // a new check isn't immediately overridden by a stale progress bar.
    LaunchedEffect(checkState) {
        if (checkState !is UpdateCheckState.UpdateAvailable) {
            viewModel.resetDownloadState()
        }
    }

    UpdateDialog(
        checkState = checkState,
        downloadState = downloadState,
        onDownload = { info -> viewModel.startDownload(info) },
        onInstall = { apkPath ->
            val intent = installer.buildInstallIntent(apkPath)
            if (intent == null) {
                Timber.w("Installer intent unavailable for %s", apkPath)
                viewModel.resetDownloadState()
            } else {
                runCatching { context.startActivity(intent) }
                    .onFailure { Timber.w(it, "Failed to launch installer") }
            }
        },
        onDismiss = { info -> viewModel.dismissInfo(info) },
        onCancelDownload = { viewModel.resetDownloadState() },
        onDismissFailure = { viewModel.check(force = true) }
    )
}
