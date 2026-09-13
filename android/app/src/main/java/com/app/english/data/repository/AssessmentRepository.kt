package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.AssessmentAnswerRequestDto
import com.app.english.data.remote.AssessmentCompleteRequestDto
import com.app.english.data.remote.AssessmentStartRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.data.remote.toJudgementOrNull
import com.app.english.domain.model.AssessmentAnswerOutcome
import com.app.english.domain.model.AssessmentBank
import com.app.english.domain.model.AssessmentJudgement
import com.app.english.domain.model.AssessmentSession
import javax.inject.Inject
import javax.inject.Singleton

/**
 * CEFR 测评链路(计划 §5.3/§5.5-3): 开考 -> 逐题作答 -> 收卷判级(202 + 轮询)。
 *
 * attempt 归属/状态机/幂等全部由服务端把关(`assessment.py`), 客户端只负责带
 * `device_id` 与把 400 `TRANSCRIPT_UNAVAILABLE` 之类的错误码透传给界面层做分支引导。
 * 判级是异步的(生产实锤: 免费额度限速会拖过 30s): [complete] 返回 null = 判级在途,
 * 去 [judgeResult] 轮询到终态; 非 null = 直接拿到终态(旧后端同步路径/幂等回放)。
 */
interface AssessmentRepository {
    suspend fun bank(): AssessmentBank

    suspend fun start(): AssessmentSession

    /** 文本与音频二选一; 音频转写不出时后端 400 `TRANSCRIPT_UNAVAILABLE`。 */
    suspend fun answer(
        attemptId: String,
        questionNo: Int,
        text: String?,
        audioB64: String?
    ): AssessmentAnswerOutcome

    /** 收卷判级; 返回 null = 判级在途(轮询 [judgeResult]), 非 null = 终态。 */
    suspend fun complete(attemptId: String): AssessmentJudgement?

    /** 判级结果轮询; 仍在途返回 null, completed 返回终态。 */
    suspend fun judgeResult(attemptId: String): AssessmentJudgement?
}

@Singleton
class AssessmentRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: SettingsStore
) : AssessmentRepository {

    override suspend fun bank() = api.getAssessmentBank().toDomain()

    override suspend fun start() = api.startAssessment(
        AssessmentStartRequestDto(deviceId = settingsStore.deviceId)
    ).toDomain()

    override suspend fun answer(
        attemptId: String,
        questionNo: Int,
        text: String?,
        audioB64: String?
    ) = api.submitAssessmentAnswer(
        attemptId = attemptId,
        request = AssessmentAnswerRequestDto(
            deviceId = settingsStore.deviceId,
            questionNo = questionNo,
            text = text,
            audioB64 = audioB64
        )
    ).toDomain()

    override suspend fun complete(attemptId: String): AssessmentJudgement? = api.completeAssessment(
        attemptId = attemptId,
        request = AssessmentCompleteRequestDto(
            deviceId = settingsStore.deviceId,
            asyncJudge = true
        )
    ).toJudgementOrNull()

    override suspend fun judgeResult(attemptId: String): AssessmentJudgement? =
        api.getAssessmentResult(attemptId, settingsStore.deviceId).toJudgementOrNull()
}
