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
     *
     * [silent] = true 时失败**不外露**: 后端不可用时只记日志, UI 保持原状。
     * 给「回前台自动重查」这类用户没发起、也没有地方处理的检查用。
     */
    suspend fun checkForUpdate(force: Boolean = false, silent: Boolean = false): UpdateCheckState {
        val current = currentVersion
        return try {
            decideUpdate(
                current = current,
                remote = repository.getAppVersion(),
                dismissedVersion = settingsStore.getDismissedUpdateVersion(),
                force = force
            )
        } catch (e: Exception) {
            // v2.2.4/VC13: 原始异常只进日志, 绝不进 UI —— kotlinx.serialization
            // / retrofit 的 message 会把整段响应体(HTML 错误页)嵌进来。
            Timber.e(e, "Update check failed (silent=%b)", silent)
            // silent: 失败不外露(只日志), 冷启动与手动检查仍照常弹「检查更新失败」。
            collapseSilentFailure(sanitizeUpdateFailureMessage(e), silent)
        }
    }

    fun markVersionDismissed(version: String) {
        settingsStore.setDismissedUpdateVersion(version)
    }
}

/** 更新检查失败时给用户的固定友好文案。 */
const val UPDATE_CHECK_FAILURE_MESSAGE = "无法连接更新服务，请检查网络后重试"

/**
 * 静默检查的失败不外露 (纯函数, JVM 可测)。
 *
 * 一次「回前台自动重查」是用户没发起、也没有地方处理的动作, 后端宕机时不该拿
 * 模态弹窗去打断他 —— 那正是 v2.2.3 及以前把用户困在「知道了 → 立刻重查 → 又失败」
 * 循环里的入口。静默失败之后 UI 保持 Idle, 冷启动与手动检查仍然弹。
 */
internal fun collapseSilentFailure(message: String, silent: Boolean): UpdateCheckState =
    if (silent) UpdateCheckState.Idle else UpdateCheckState.Failed(message)

/**
 * 关掉失败弹窗后的状态 (纯函数, JVM 可测): [UpdateCheckState.Failed] →
 * [UpdateCheckState.Idle], 其它状态原样保留(弹窗只在 Failed 时出现)。
 *
 * 之前 `onDismissFailure` 挂的是 `check(force = true)`, 后端一挂就是「知道了 →
 * 立刻重查 → 又失败 → 弹窗回来」的死循环, Settings(改服务器地址的入口)永远进不去。
 * 本版起 dismiss 只做这一个状态转移, 不再触发任何网络请求。
 */
internal fun dismissedFailureState(state: UpdateCheckState): UpdateCheckState =
    if (state is UpdateCheckState.Failed) UpdateCheckState.Idle else state

/**
 * 把异常折叠成一句可上屏的中文 (纯函数, JVM 可测)。
 *
 * 规则与 `data.remote.BackendErrorText` 同源且更保守:
 * 只有**本来就是中文、不含 HTML/JSON 残片、不超长**的消息才保留
 * (如 `IOException("无法连接更新服务")`), 其余一律回落到 [UPDATE_CHECK_FAILURE_MESSAGE]。
 * kotlinx.serialization / Retrofit 抛出的异常消息多为英文诊断串
 * (甚至内嵌响应体), 直接 `e.message` 上屏就是本次线上事故的 UX 表现。
 */
internal fun sanitizeUpdateFailureMessage(e: Throwable): String {
    val raw = e.message?.trim().orEmpty()
    val looksClean = raw.length <= MAX_KEPT_FAILURE_LENGTH &&
        raw.none { it == '<' || it == '{' || it == '}' } &&
        raw.any { it in '\u4E00'..'\u9FFF' }
    return if (raw.isNotEmpty() && looksClean) raw else UPDATE_CHECK_FAILURE_MESSAGE
}

private const val MAX_KEPT_FAILURE_LENGTH = 80

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
