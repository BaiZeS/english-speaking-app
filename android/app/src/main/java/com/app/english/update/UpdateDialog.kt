package com.app.english.update

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Renders the auto-update prompt + progress overlay.
 *
 * Hosting Activity should observe [AppUpdateViewModel.checkState] / [downloadState]
 * and pass the latest non-Idle state to this composable. The dialog itself does
 * NOT call into the installer; it surfaces ``onDownload`` and ``onInstall`` so the
 * caller can wire it to [ApkInstaller] together with the system permission flow.
 */
@Composable
// v2.2.4: 新增 onOpenSettings（失败弹窗的「进入设置」逃生门）后达 8 参。回调式 Composable
// 的参数本来就是一排事件通道，强拆数据类反而丢可读性 —— 处置口径同 BriefingViewModel。
@Suppress("LongParameterList")
fun UpdateDialog(
    checkState: UpdateCheckState,
    downloadState: DownloadState,
    onDownload: (UpdateInfo) -> Unit,
    onInstall: (apkPath: String) -> Unit,
    onDismiss: (UpdateInfo) -> Unit,
    onCancelDownload: () -> Unit,
    onDismissFailure: () -> Unit,
    onOpenSettings: () -> Unit
) {
    when (checkState) {
        UpdateCheckState.Idle, UpdateCheckState.Checking, is UpdateCheckState.UpToDate -> Unit
        is UpdateCheckState.Failed -> FailureDialog(
            message = checkState.message,
            onDismissFailure = onDismissFailure,
            onOpenSettings = onOpenSettings
        )
        is UpdateCheckState.UpdateAvailable -> PromptDialog(
            info = checkState.info,
            downloadState = downloadState,
            onDownload = onDownload,
            onInstall = onInstall,
            onDismiss = onDismiss,
            onCancelDownload = onCancelDownload
        )
    }
}

/**
 * 「检查更新失败」弹窗 (v2.2.4/VC13)。
 *
 * 三个出口: 「知道了」与点弹窗外/返回键都只做 Failed → Idle; 「进入设置」在关窗之后
 * 把用户送到能改服务器地址的那一页。旧版这里挂的是 `check(force = true)` —— 后端不可用时
 * 弹窗关掉就立刻回来, 用户被模态框锁死在任何页面(包括「设置」)之外。
 */
@Composable
private fun FailureDialog(
    message: String,
    onDismissFailure: () -> Unit,
    onOpenSettings: () -> Unit
) {
    AlertDialog(
        onDismissRequest = onDismissFailure,
        confirmButton = { TextButton(onClick = onDismissFailure) { Text("知道了") } },
        dismissButton = { TextButton(onClick = onOpenSettings) { Text("进入设置") } },
        title = { Text("检查更新失败") },
        text = { Text(message) }
    )
}

@Composable
private fun PromptDialog(
    info: UpdateInfo,
    downloadState: DownloadState,
    onDownload: (UpdateInfo) -> Unit,
    onInstall: (String) -> Unit,
    onDismiss: (UpdateInfo) -> Unit,
    onCancelDownload: () -> Unit
) {
    LaunchedEffect(downloadState) {
        if (downloadState is DownloadState.Downloaded) {
            onInstall(downloadState.apkPath)
        }
    }
    AlertDialog(
        onDismissRequest = { if (!info.forceUpdate) onDismiss(info) },
        title = { Text(if (info.forceUpdate) "需要更新" else "发现新版本 ${info.latestVersion}") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Text("当前版本：${info.currentVersion}", style = MaterialTheme.typography.bodyMedium)
                if (info.releaseNotes.isNotBlank()) {
                    Text("更新内容：", style = MaterialTheme.typography.titleSmall)
                    Text(info.releaseNotes, style = MaterialTheme.typography.bodyMedium)
                }
                when (val state = downloadState) {
                    is DownloadState.Downloading -> {
                        Text("下载中 ${state.progress}%", style = MaterialTheme.typography.bodyMedium)
                        LinearProgressIndicator(
                            progress = (state.progress / 100f),
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                    is DownloadState.Failed -> {
                        Text(
                            "下载失败：${state.message}",
                            color = MaterialTheme.colorScheme.error,
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                    is DownloadState.Downloaded -> {
                        Text(
                            "下载完成，准备安装…",
                            style = MaterialTheme.typography.bodyMedium
                        )
                    }
                    DownloadState.Idle -> Unit
                }
            }
        },
        confirmButton = {
            when (downloadState) {
                DownloadState.Idle, is DownloadState.Failed -> {
                    TextButton(onClick = { onDownload(info) }) { Text("下载更新") }
                }
                is DownloadState.Downloading -> {
                    TextButton(onClick = onCancelDownload) { Text("取消") }
                }
                is DownloadState.Downloaded -> {
                    TextButton(onClick = { onInstall(downloadState.apkPath) }) { Text("安装") }
                }
            }
        },
        dismissButton = {
            if (!info.forceUpdate && downloadState !is DownloadState.Downloading) {
                TextButton(onClick = { onDismiss(info) }) { Text("稍后") }
            } else if (info.forceUpdate && downloadState is DownloadState.Failed) {
                TextButton(onClick = { onDownload(info) }) { Text("重试") }
            }
        }
    )
}

@Composable
@Suppress("UnusedPrivateMember") // kept for symmetry; helpers future-proofed for hint UI
private fun VersionRow(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, style = MaterialTheme.typography.bodyMedium)
        Text(value, style = MaterialTheme.typography.bodyMedium)
    }
}
