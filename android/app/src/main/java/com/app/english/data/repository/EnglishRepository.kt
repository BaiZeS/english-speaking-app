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
    suspend fun getTtsAudio(text: String, voice: String): com.app.english.domain.model.TtsAudio
    suspend fun score(
        lessonId: Int? = null,
        lineId: String? = null,
        refText: String,
        audioBase64: String,
        mode: String = "k12",
        category: String = "read_sentence"
    ): ScoreResult
    suspend fun generateDialogue(
        scene: String,
        mode: String = "adult",
        modelId: String? = null
    ): DialogueSession = error("Dialogue generation is not supported by this repository")

    /**
     * @param shownSuggestions §A4/A5: 最近已经**展示给学员**的参考句 (≤8), 服务端拿它防
     *   复写 (自由对话没有会话表, 参考句每轮被覆盖, 只有客户端知道给过哪几句)。
     */
    suspend fun dialogueTurn(
        sceneId: String,
        history: List<DialogueMessageDto>,
        userAudioBase64: String,
        modelId: String? = null,
        shownSuggestions: List<String> = emptyList()
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
    suspend fun getLessonProgress(
        book: String,
        lessonId: Int
    ): com.app.english.domain.model.LessonProgress =
        error("Lesson progress lookup is not supported by this repository")
}

@Singleton
class EnglishRepositoryImpl @Inject constructor(
    private val api: EnglishApi,
    private val settingsStore: com.app.english.data.local.SettingsStore
) : EnglishRepository {
    override suspend fun listLessons(book: String): List<LessonSummary> =
        api.listLessons(book).map { it.toDomain() }

    override suspend fun getLessonRoles(lessonId: Int, book: String): LessonDetail =
        api.getLessonRoles(lessonId, book).toDomain()

    override suspend fun getTtsAudio(
        text: String,
        voice: String
    ): com.app.english.domain.model.TtsAudio = api.getTts(text, voice).toDomain()

    override suspend fun score(
        lessonId: Int?,
        lineId: String?,
        refText: String,
        audioBase64: String,
        mode: String,
        category: String
    ): ScoreResult {
        val request = ScoreRequestDto(
            lessonId = lessonId,
            lineId = lineId,
            refText = refText,
            mode = mode,
            category = category,
            audio = audioBase64
        )
        return api.score(request).toDomain()
    }

    override suspend fun generateDialogue(
        scene: String,
        mode: String,
        modelId: String?
    ): DialogueSession = api.generateDialogue(
        // 身份 add-only (§3 C3b): 自定义场景的开场白按归属解行, 目录场景不受影响。
        DialogueGenerateRequestDto(
            scene = scene,
            mode = mode,
            modelId = modelId,
            deviceId = settingsStore.deviceId
        )
    ).toDomain()

    override suspend fun dialogueTurn(
        sceneId: String,
        history: List<DialogueMessageDto>,
        userAudioBase64: String,
        modelId: String?,
        shownSuggestions: List<String>
    ): DialogueTurn = api.dialogueTurn(
        DialogueTurnRequestDto(
            sceneId = sceneId,
            history = history,
            userAudioB64 = userAudioBase64,
            modelId = modelId,
            deviceId = settingsStore.deviceId,
            shownSuggestions = shownSuggestions
        )
    ).toDomain()

    override suspend fun listLlmModels(): List<LlmModel> =
        api.listLlmModels().models.map { it.toDomain() }

    override suspend fun getAppVersion(): AppVersion = api.getAppVersion().toDomain()

    override suspend fun listBooks(): List<Book> = api.listBooks().books.map { it.toDomain() }

    override suspend fun listDialogueScenes(): List<DialogueScene> =
        api.listDialogueScenes(settingsStore.deviceId).scenes.map { it.toDomain() }

    override suspend fun getStats(deviceId: String): PracticeStats =
        api.getStats(deviceId).toDomain()

    override suspend fun getLessonProgress(
        book: String,
        lessonId: Int
    ): com.app.english.domain.model.LessonProgress =
        api.getLessonProgress(lessonId, book, settingsStore.deviceId).toDomain()
}
