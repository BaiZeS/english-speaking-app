package com.app.english.audio

import androidx.media3.common.PlaybackException

/**
 * 把 ExoPlayer 错误码折叠成人话。
 *
 * 为什么非得上屏：v2.3.0 及以前 `onPlayerError` 只写 Timber 再调 completionCallback，
 * UI 把「播放失败」当「播完」，华为/鸿蒙上就是「所有声音都不出声、什么提示都没有」；
 * 而 release 构建连 Timber tree 都没 plant（EnglishAssistantApp.kt:12），
 * 现场也没日志可取。屏幕上的错误码就是下一个现场的证据。
 */
internal fun audioPlaybackErrorMessage(errorCode: Int): String = when (errorCode) {
    PlaybackException.ERROR_CODE_AUDIO_TRACK_INIT_FAILED,
    PlaybackException.ERROR_CODE_AUDIO_TRACK_WRITE_FAILED,
    PlaybackException.ERROR_CODE_AUDIO_TRACK_OFFLOAD_INIT_FAILED,
    PlaybackException.ERROR_CODE_AUDIO_TRACK_OFFLOAD_WRITE_FAILED ->
        "这台设备的音频输出放不了当前语音规格，请截图并把错误码发给开发者（错误码 $errorCode）"

    PlaybackException.ERROR_CODE_PARSING_CONTAINER_UNSUPPORTED,
    PlaybackException.ERROR_CODE_PARSING_CONTAINER_MALFORMED,
    PlaybackException.ERROR_CODE_DECODER_INIT_FAILED,
    PlaybackException.ERROR_CODE_DECODING_FORMAT_UNSUPPORTED ->
        "语音无法解码，请截图并把错误码发给开发者（错误码 $errorCode）"

    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_FAILED,
    PlaybackException.ERROR_CODE_IO_NETWORK_CONNECTION_TIMEOUT ->
        "连不上服务器，播不了语音。检查网络或「设置」里的服务器地址（错误码 $errorCode）"

    PlaybackException.ERROR_CODE_IO_BAD_HTTP_STATUS,
    PlaybackException.ERROR_CODE_IO_FILE_NOT_FOUND ->
        "服务器上找不到这段语音（错误码 $errorCode）"

    PlaybackException.ERROR_CODE_IO_CLEARTEXT_NOT_PERMITTED ->
        "本机不允许 http 明文播放，请在「设置」改用允许的服务器地址（错误码 $errorCode）"

    else -> "语音播放失败，请重试（错误码 $errorCode）"
}
