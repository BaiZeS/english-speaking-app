package com.app.english.data.repository

import com.app.english.data.local.SettingsStore
import com.app.english.data.remote.AssessmentAnswerRequestDto
import com.app.english.data.remote.AssessmentCompleteRequestDto
import com.app.english.data.remote.AssessmentStartRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.AssessmentAnswerOutcome
import com.app.english.domain.model.AssessmentBank
import com.app.english.domain.model.AssessmentJudgement
import com.app.english.domain.model.AssessmentSession
import javax.inject.Inject
import javax.inject.Singleton

/**
 * CEFR 测评链路(计划 §5.3/§5.5-3): 开考 -> 逐题作答 -> 收卷判级。
 *
 * 纯转发仓库: attempt 归属/状态机/幂等全部由服务端把关(`assessment.py`),
 * 客户端只负责带 `device_id` 与把 400 `TRANSCRIPT_UNAVAILABLE` 之类的错误码
 * 透传给界面层做分支引导。
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

    /** 一次批量 LLM 判级; 幂等(已完成重放同形状)。 */
    suspend fun complete(attemptId: String): AssessmentJudgement
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

    override suspend fun complete(attemptId: String): AssessmentJudgement = api.completeAssessment(
        attemptId = attemptId,
        request = AssessmentCompleteRequestDto(
            deviceId = settingsStore.deviceId
        )
    ).toDomain()
}
