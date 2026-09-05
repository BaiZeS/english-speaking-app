package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.AbilityResponseDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.AbilityProfile
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 能力画像读路径(计划 §5.6): `GET /ability?device_id=&days=`。
 *
 * `days` 只接受 7/30/90(后端 400 ABILITY_DAYS_INVALID), 客户端在门口就夹到
 * 合法值, 让 UI 的分段切换永远发得出合法请求。
 */
interface AbilityRepository {
    /** @param days 轨迹窗口; 非法值会被 [sanitizeAbilityDays] 归到默认 30。 */
    suspend fun getProfile(days: Int = DEFAULT_ABILITY_DAYS): AbilityProfile
}

const val DEFAULT_ABILITY_DAYS: Int = 30

/** 轨迹窗口白名单(§5.3: days=7|30|90)。 */
val ALLOWED_ABILITY_DAYS: Set<Int> = setOf(7, 30, 90)

fun sanitizeAbilityDays(days: Int): Int =
    if (days in ALLOWED_ABILITY_DAYS) days else DEFAULT_ABILITY_DAYS

@Singleton
class AbilityRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : AbilityRepository {
    override suspend fun getProfile(days: Int): AbilityProfile {
        val response: AbilityResponseDto =
            api.getAbility(settingsStore.deviceId, sanitizeAbilityDays(days))
        return response.toDomain()
    }
}
