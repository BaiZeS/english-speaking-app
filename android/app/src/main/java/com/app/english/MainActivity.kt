package com.app.english

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.viewModels
import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.data.local.SettingsStore
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

    @Inject lateinit var settingsStore: SettingsStore

    private val updateViewModel: AppUpdateViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            val themeMode = settingsStore.getThemeMode()
            val systemDark = isSystemInDarkTheme()
            val useDark = when (themeMode) {
                SettingsStore.THEME_LIGHT -> false
                SettingsStore.THEME_DARK -> true
                else -> systemDark
            }
            EnglishAssistantTheme(darkTheme = useDark) {
                AppNavHost()
                UpdateHost(updateViewModel, apkInstaller)
            }
        }
        updateViewModel.check()
    }

    override fun onResume() {
        super.onResume()
        updateViewModel.check()
    }
}

@Composable
private fun UpdateHost(viewModel: AppUpdateViewModel, installer: ApkInstaller) {
    val checkState by viewModel.checkState.collectAsStateWithLifecycle()
    val downloadState by viewModel.downloadState.collectAsStateWithLifecycle()
    val context = LocalContext.current

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
