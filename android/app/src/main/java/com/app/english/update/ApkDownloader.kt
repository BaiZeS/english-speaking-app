package com.app.english.update

import android.content.Context
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import java.io.IOException
import javax.inject.Inject
import javax.inject.Singleton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.flow.flowOn
import okhttp3.OkHttpClient
import okhttp3.Request
import timber.log.Timber

/**
 * Streams an APK from the backend's release URL into the app's private files dir and
 * emits download progress (0-100). The downloaded file is then handed off to
 * [com.app.english.update.ApkInstaller] which opens it via FileProvider.
 *
 * We intentionally do not depend on DownloadManager: we want a foreground-friendly
 * in-process download that emits progress to a Compose state holder without
 * requiring POST_NOTIFICATIONS (which only ships on Android 13+).
 */
@Singleton
class ApkDownloader @Inject constructor(
    @ApplicationContext private val context: Context,
    private val client: OkHttpClient
) {
    /**
     * Download [url] to a deterministic ``updates/app-<version>.apk`` path under
     * the app's internal `files/updates` dir. Re-downloading the same version
     * overwrites the prior file so failed attempts don't accumulate.
     */
    fun download(url: String, version: String): Flow<DownloadState> = flow {
        if (url.isBlank()) {
            emit(DownloadState.Failed("更新地址为空，请联系管理员配置 APP_APK_URL"))
            return@flow
        }
        val target = targetFile(version)
        target.parentFile?.mkdirs()
        val request = Request.Builder().url(url).build()
        try {
            client.newCall(request).execute().use { response ->
                if (!response.isSuccessful) {
                    emit(DownloadState.Failed("下载失败：HTTP ${response.code}"))
                    return@flow
                }
                val body = response.body
                if (body == null) {
                    emit(DownloadState.Failed("下载失败：响应为空"))
                    return@flow
                }
                val total = body.contentLength().takeIf { it > 0 } ?: -1L
                body.byteStream().use { input ->
                    target.outputStream().use { output ->
                        val buf = ByteArray(DEFAULT_BUFFER_SIZE)
                        var read: Int
                        var emitted = 0
                        var copied = 0L
                        while (input.read(buf).also { read = it } != -1) {
                            output.write(buf, 0, read)
                            copied += read
                            if (total > 0) {
                                val progress = ((copied * 100) / total).toInt().coerceIn(0, 100)
                                if (progress - emitted >= 5 || progress == 100) {
                                    emit(DownloadState.Downloading(progress))
                                    emitted = progress
                                }
                            }
                        }
                    }
                }
                emit(DownloadState.Downloading(100))
                emit(DownloadState.Downloaded(target.absolutePath))
            }
        } catch (e: IOException) {
            Timber.e(e, "APK download failed url=$url")
            // Don't leave a partial file behind; the next attempt can start clean.
            if (target.exists()) target.delete()
            emit(DownloadState.Failed("下载失败：${e.message ?: "网络错误"}"))
        } catch (e: Exception) {
            Timber.e(e, "APK download crashed url=$url")
            if (target.exists()) target.delete()
            emit(DownloadState.Failed("下载失败：${e.message ?: "未知错误"}"))
        }
    }.flowOn(Dispatchers.IO)

    private fun targetFile(version: String): File {
        val sanitized = version.ifBlank { "latest" }.replace(Regex("[^A-Za-z0-9._-]"), "_")
        return File(context.filesDir, "updates/app-$sanitized.apk")
    }

    companion object {
        private const val DEFAULT_BUFFER_SIZE = 16 * 1024
    }
}
