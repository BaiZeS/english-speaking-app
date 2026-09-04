package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.CreateSessionRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.MissionTurnRequestDto
import com.app.english.data.remote.StepAttemptRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.data.remote.toHintData
import com.app.english.domain.model.ContinueSession
import com.app.english.domain.model.HintData
import com.app.english.domain.model.MissionTurnResult
import com.app.english.domain.model.SessionSnapshot
import javax.inject.Inject
import javax.inject.Singleton

/**
 * 通关会话状态机的客户端通道(计划 §5.3): 状态全在服务端, 客户端只发音频/文本,
 * 每次响应带回整份进度 —— 崩了用 [get] 恢复, 这里不做任何本地推断。
 *
 * 与 [SceneRepository] 同纪律: 失败原样抛给 ViewModel, 不吞异常不假装成功。
 */
interface SessionRepository {
    /** 开场: 建会话并返回整课快照 + 打基础清单。 */
    suspend fun create(sceneId: String): SessionSnapshot

    /** 崩溃恢复快照(按服务端状态机渲染, 客户端不自算进度)。 */
    suspend fun get(sessionId: String): SessionSnapshot

    /** 最近会话摘要; `status=active` 只回没打完的场。 */
    suspend fun list(status: String = ""): List<ContinueSession>

    suspend fun submitStep(
        sessionId: String,
        stepId: String,
        text: String?,
        audioB64: String? = null
    ): DrillOutcome

    suspend fun skipStep(sessionId: String, stepId: String): DrillOutcome

    /** 实战一轮: 文本或音频二选一。 */
    suspend fun missionTurn(sessionId: String, text: String?, audioB64: String?): MissionTurnResult

    /** 要提示: 标记下一个判定回合 costs_score。 */
    suspend fun hint(sessionId: String): HintData

    /** 主动收工 -> 复盘报告。 */
    suspend fun finishMission(sessionId: String): MissionTurnResult
}

/** `/step` 与 `/skip-step` 的返回(评分 + 清单进度 + 是否解锁实战)。 */
data class DrillOutcome(
    val grade: com.app.english.domain.model.DrillGradeResult,
    val briefing: com.app.english.domain.model.BriefingProgress,
    val unlockedMission: Boolean
)

@Singleton
class SessionRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : SessionRepository {

    override suspend fun create(sceneId: String): SessionSnapshot = api.createSession(
        CreateSessionRequestDto(deviceId = settingsStore.deviceId, sceneId = sceneId)
    ).toDomain()

    override suspend fun get(sessionId: String): SessionSnapshot =
        api.getSession(sessionId, settingsStore.deviceId).toDomain()

    override suspend fun list(status: String): List<ContinueSession> =
        api.listSessions(settingsStore.deviceId, status).map { it.toDomain() }

    override suspend fun submitStep(
        sessionId: String,
        stepId: String,
        text: String?,
        audioB64: String?
    ): DrillOutcome {
        val response = api.submitStep(
            sessionId,
            StepAttemptRequestDto(
                deviceId = settingsStore.deviceId,
                stepId = stepId,
                text = text,
                audioB64 = audioB64
            )
        )
        return DrillOutcome(
            response.grade.toDomain(),
            response.briefing.toDomain(),
            response.unlockedMission
        )
    }

    override suspend fun skipStep(sessionId: String, stepId: String): DrillOutcome {
        val response = api.skipStep(
            sessionId,
            StepAttemptRequestDto(deviceId = settingsStore.deviceId, stepId = stepId)
        )
        return DrillOutcome(
            response.grade.toDomain(),
            response.briefing.toDomain(),
            response.unlockedMission
        )
    }

    override suspend fun missionTurn(
        sessionId: String,
        text: String?,
        audioB64: String?
    ): MissionTurnResult = api.submitMissionTurn(
        sessionId,
        MissionTurnRequestDto(
            deviceId = settingsStore.deviceId,
            text = text?.takeIf { it.isNotBlank() },
            audioB64 = audioB64?.takeIf { it.isNotBlank() }
        )
    ).toDomain()

    override suspend fun hint(sessionId: String): HintData = api.requestHint(
        sessionId,
        MissionTurnRequestDto(deviceId = settingsStore.deviceId)
    ).toHintData()

    override suspend fun finishMission(sessionId: String): MissionTurnResult {
        val response = api.finishMission(
            sessionId,
            MissionTurnRequestDto(deviceId = settingsStore.deviceId)
        )
        // 收工响应里没有单轮语义: 把报告包进 turn-less 的结果(界面只读 review)。
        return MissionTurnResult(
            turn = com.app.english.domain.model.MissionTurn(
                turnIndex = 0,
                transcript = "",
                reply = "",
                suggestion = ""
            ),
            checklist = response.report.checklist.map { it.toDomain() },
            cleared = response.report.cleared,
            turnCount = response.report.turnCount,
            maxTurns = response.report.maxTurns,
            autoFinished = response.report.autoFinished,
            finished = true,
            costsScore = false,
            source = response.report.source,
            llmSource = response.report.llmSource,
            review = response.report.toDomain()
        )
    }
}
