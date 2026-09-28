package com.app.english.update

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

@HiltViewModel
class AppUpdateViewModel @Inject constructor(
    private val updateManager: AppUpdateManager,
    private val downloader: ApkDownloader
) : ViewModel() {
    private val _checkState = MutableStateFlow<UpdateCheckState>(UpdateCheckState.Idle)
    val checkState: StateFlow<UpdateCheckState> = _checkState.asStateFlow()

    private val _downloadState = MutableStateFlow<DownloadState>(DownloadState.Idle)
    val downloadState: StateFlow<DownloadState> = _downloadState.asStateFlow()

    /**
     * [silent] 见 [AppUpdateManager.checkForUpdate] —— 静默检查失败只记日志、不弹窗
     * (回前台自动重查走这条路)。
     */
    fun check(force: Boolean = false, silent: Boolean = false) {
        if (_checkState.value is UpdateCheckState.Checking) return
        _checkState.update { UpdateCheckState.Checking }
        viewModelScope.launch {
            _checkState.update { updateManager.checkForUpdate(force = force, silent = silent) }
        }
    }

    /**
     * 关闭「检查更新失败」弹窗: [UpdateCheckState.Failed] → [UpdateCheckState.Idle],
     * **不再立刻重查**。
     *
     * 之前这里挂的是 `check(force = true)`: 后端不可用时「知道了」= 立刻再失败一次 = 弹窗
     * 原样回来, 用户永远进不去「设置」(改服务器地址的入口就在那一页), 等于被模态框锁死。
     */
    fun dismissFailure() {
        _checkState.update { dismissedFailureState(it) }
    }

    fun startDownload(info: UpdateInfo) {
        if (info.apkUrl.isBlank()) {
            _downloadState.update { DownloadState.Failed("未配置 APK 下载地址") }
            return
        }
        if (_downloadState.value is DownloadState.Downloading) return
        _downloadState.update { DownloadState.Downloading(0) }
        viewModelScope.launch {
            downloader.download(info.apkUrl, info.latestVersion).collect { state ->
                _downloadState.update { state }
            }
        }
    }

    fun dismissInfo(info: UpdateInfo) {
        updateManager.markVersionDismissed(info.latestVersion)
        _checkState.update { UpdateCheckState.Idle }
    }

    fun resetDownloadState() {
        _downloadState.update { DownloadState.Idle }
    }
}
