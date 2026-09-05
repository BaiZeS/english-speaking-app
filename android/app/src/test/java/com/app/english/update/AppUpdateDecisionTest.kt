package com.app.english.update

import com.app.english.domain.model.AppVersion
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * P8·2e: dismiss 语义的行为锁 (与后端 version.py 的 0.0.0 哨兵成对)。
 *
 * 关键回归: 服务端**未配置**最低版本时回发 min_supported="0.0.0";
 * 1.4.0 客户端必须走常规可关路径 —— 「稍后再说」过的版本不再弹出,
 * 手动检查 (force=true) 仍能重新弹出。只有显式收紧 min 且本机低于它,
 * 才无视 dismissed 必弹。此前后端默认 min=latest, 所有旧包被判「不支持」。
 */
class AppUpdateDecisionTest {
    private fun version(latest: String, minSupported: String, forceFlag: Boolean = false) =
        AppVersion(
            latestVersion = latest,
            minSupportedVersion = minSupported,
            apkUrl = "https://example.invalid/app-release.apk",
            releaseNotes = "v2.0.0",
            forceUpdate = forceFlag
        )

    @Test
    fun serverDefaultSentinel_neverMarksOldClientUnsupported() {
        // 旧后端 bug 的正面回归: min=0.0.0 + current=1.4.0 -> 常规升级提示, 可 dismiss。
        val state =
            decideUpdate("1.4.0", version("2.0.0", "0.0.0"), dismissedVersion = null, force = false)
        assertTrue(state is UpdateCheckState.UpdateAvailable)
        assertEquals("2.0.0", (state as UpdateCheckState.UpdateAvailable).info.latestVersion)
    }

    @Test
    fun dismissedVersion_staysSilent_whenNotForcedAndSupported() {
        val remote = version("2.0.0", "0.0.0")
        assertEquals(
            UpdateCheckState.UpToDate("1.4.0"),
            decideUpdate("1.4.0", remote, dismissedVersion = "2.0.0", force = false)
        )
        // 用户点了「稍后再说」跳过 1.9.0, 服务端又发了 2.0.0 -> 新提醒照常弹。
        assertTrue(
            decideUpdate("1.4.0", remote, dismissedVersion = "1.9.0", force = false)
                is UpdateCheckState.UpdateAvailable
        )
    }

    @Test
    fun manualCheck_bypassesDismissal() {
        val remote = version("2.0.0", "0.0.0")
        assertTrue(
            decideUpdate("1.4.0", remote, dismissedVersion = "2.0.0", force = true)
                is UpdateCheckState.UpdateAvailable
        )
    }

    @Test
    fun explicitMinAboveCurrent_ignoresDismissal_andCarriesServerForce() {
        // 运维显式配置 APP_MIN_SUPPORTED_VERSION=2.0.0: 1.4.0 被判不支持, 必弹。
        val remote = version("2.1.0", "2.0.0", forceFlag = true)
        val state = decideUpdate("1.4.0", remote, dismissedVersion = "2.1.0", force = false)
        assertTrue(state is UpdateCheckState.UpdateAvailable)
        assertEquals(true, (state as UpdateCheckState.UpdateAvailable).info.forceUpdate)
    }

    @Test
    fun currentAtOrAboveLatest_isUpToDate() {
        assertEquals(
            UpdateCheckState.UpToDate("2.0.0"),
            decideUpdate("2.0.0", version("2.0.0", "0.0.0"), dismissedVersion = null, force = false)
        )
        assertEquals(
            UpdateCheckState.UpToDate("2.0.1"),
            decideUpdate("2.0.1", version("2.0.0", "0.0.0"), dismissedVersion = null, force = true)
        )
    }
}
