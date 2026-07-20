package com.app.english.data.repository

import com.app.english.data.remote.DialogueGenerateRequestDto
import com.app.english.data.remote.DialogueMessageDto
import com.app.english.data.remote.DialogueTurnRequestDto
import com.app.english.data.remote.EnglishApi
import com.app.english.data.remote.ScoreRequestDto
import com.app.english.data.remote.toDomain
import com.app.english.domain.model.AppVersion
import com.app.english.domain.model.Book
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.DialogueSession
import com.app.english.domain.model.DialogueTurn
import com.app.english.domain.model.LessonDetail
import com.app.english.domain.model.LessonSummary
import com.app.english.domain.model.LlmModel
import com.app.english.domain.model.PracticeStats
import com.app.english.domain.model.ScoreResult
import javax.inject.Inject
import javax.inject.Singleton

interface EnglishRepository {
    suspend fun listLessons(book: String): List<LessonSummary>
    suspend fun getLessonRoles(lessonId: Int, book: String): LessonDetail
    suspend fun getTtsAudioUrl(text: String, voice: String): String
    suspend fun score(
        lessonId: Int,
        lineId: String,
        refText: String,
        audioBase64: String,
        mode: String = "k12"
    ): ScoreResult
    suspend fun generateDialogue(
        scene: String,
        mode: String = "adult",
        modelId: String? = null
    ): DialogueSession = error("Dialogue generation is not supported by this repository")
    suspend fun dialogueTurn(
        sceneId: String,
        history: List<DialogueMessageDto>,
        userAudioBase64: String,
        modelId: String? = null
    ): DialogueTurn = error("Dialogue turns are not supported by this repository")
    suspend fun listLlmModels(): List<LlmModel> =
        error("LLM model catalog is not supported by this repository")
    suspend fun getAppVersion(): AppVersion =
        error("App version lookup is not supported by this repository")
    suspend fun listBooks(): List<Book> = error("Books catalog is not supported by this repository")
    suspend fun listDialogueScenes(): List<DialogueScene> =
        error("Dialogue scenes catalog is not supported by this repository")
    suspend fun getStats(deviceId: String): PracticeStats =
        error("Stats lookup is not supported by this repository")
}

@Singleton
class EnglishRepositoryImpl @Inject constructor(private val api: EnglishApi) : EnglishRepository {
    override suspend fun listLessons(book: String): List<LessonSummary> =
        api.listLessons(book).map { it.toDomain() }

    override suspend fun getLessonRoles(lessonId: Int, book: String): LessonDetail =
        api.getLessonRoles(lessonId, book).toDomain()

    override suspend fun getTtsAudioUrl(text: String, voice: String): String =
        api.getTts(text, voice).audioUrl

    override suspend fun score(
        lessonId: Int,
        lineId: String,
        refText: String,
        audioBase64: String,
        mode: String
    ): ScoreResult {
        val request = ScoreRequestDto(
            lessonId = lessonId,
            lineId = lineId,
            refText = refText,
            mode = mode,
            audio = audioBase64
        )
        return api.score(request).toDomain()
    }

    override suspend fun generateDialogue(
        scene: String,
        mode: String,
        modelId: String?
    ): DialogueSession = api.generateDialogue(
        DialogueGenerateRequestDto(scene = scene, mode = mode, modelId = modelId)
    ).toDomain()

    override suspend fun dialogueTurn(
        sceneId: String,
        history: List<DialogueMessageDto>,
        userAudioBase64: String,
        modelId: String?
    ): DialogueTurn = api.dialogueTurn(
        DialogueTurnRequestDto(
            sceneId = sceneId,
            history = history,
            userAudioB64 = userAudioBase64,
            modelId = modelId
        )
    ).toDomain()

    override suspend fun listLlmModels(): List<LlmModel> =
        api.listLlmModels().models.map { it.toDomain() }

    override suspend fun getAppVersion(): AppVersion = api.getAppVersion().toDomain()

    override suspend fun listBooks(): List<Book> = api.listBooks().books.map { it.toDomain() }

    override suspend fun listDialogueScenes(): List<DialogueScene> =
        api.listDialogueScenes().scenes.map { it.toDomain() }

    override suspend fun getStats(deviceId: String): PracticeStats =
        api.getStats(deviceId).toDomain()
}
