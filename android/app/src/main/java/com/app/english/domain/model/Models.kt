package com.app.english.domain.model

data class LessonSummary(
    val id: Int,
    val book: String,
    val lessonNo: Int,
    val title: String,
    val roleCount: Int,
    val durationS: Double
)

data class Line(val id: String, val text: String, val translation: String?, val ipa: String?)

data class Role(val name: String, val lines: List<Line>)

data class LessonDetail(
    val id: Int,
    val book: String,
    val lessonNo: Int,
    val title: String,
    val roles: List<Role>
)

data class WordScore(val word: String, val score: Double, val ipa: String?)

data class ScoreResult(
    val total: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    val wordDetails: List<WordScore>,
    val suggestion: String?,
    // "xunfei"=真实评测, "stub"=占位假分. UI 据此提示用户.
    val source: String = "stub"
) {
    val isStub: Boolean get() = source != "xunfei"
}

data class TtsAudio(
    val audioUrl: String,
    val durationMs: Int,
    // "mimo"=真实合成, "stub"=占位假音频.
    val source: String = "stub"
) {
    val isStub: Boolean get() = source != "mimo"
}

data class HistoryItem(
    val id: String,
    val book: String = "nce1",
    val lessonId: Int,
    val lineId: String,
    // P8·2f: "lesson" | "scene_course" (旧后端默认 lesson)。
    val kind: String = "lesson",
    // 人读标题; 空串表示后端未升级, 渲染层回退旧版 "Lesson N · lineId"。
    val label: String = "",
    val scoreTotal: Double,
    val scorePronunciation: Double,
    val scoreFluency: Double,
    val scoreCompleteness: Double,
    val createdAt: String
)

data class DialogueLine(
    val id: String,
    val role: String,
    val text: String,
    val translation: String? = null,
    val isUser: Boolean = false
)

data class DialogueSession(
    val sceneId: String,
    val status: String,
    val title: String,
    val lines: List<DialogueLine>,
    val suggestedReply: String
)

data class DialogueTurn(
    val replyText: String,
    val suggestedReply: String,
    val recognizedText: String? = null,
    val replyAudioUrl: String? = null
)

data class LlmModel(
    val id: String,
    val displayName: String,
    val provider: String,
    val description: String
)

data class AppVersion(
    val latestVersion: String,
    val minSupportedVersion: String,
    val apkUrl: String,
    val releaseNotes: String,
    val forceUpdate: Boolean
)

data class Book(
    val id: String,
    val displayName: String,
    val description: String,
    val level: String,
    val lessonCount: Int
)

data class DialogueScene(val id: String, val title: String, val description: String)

data class DailyScore(
    val date: String,
    val avgTotal: Double,
    val avgPronunciation: Double,
    val avgFluency: Double,
    val avgCompleteness: Double,
    val sessions: Int
)

data class PracticeStats(
    val totalSessions: Int,
    val avgTotal: Double,
    val avgPronunciation: Double,
    val avgFluency: Double,
    val avgCompleteness: Double,
    val bestTotal: Double,
    val recentSessions: Int,
    val streakDays: Int,
    val daily: List<DailyScore>,
    val lessonsAttempted: List<Int>,
    val weakestLessons: List<WeakestLesson> = emptyList()
) {
    val hasData: Boolean get() = totalSessions > 0
}

data class LessonProgress(
    val book: String = "nce1",
    val lessonId: Int,
    val attemptCount: Int,
    val bestScore: Double,
    val lastScore: Double,
    val lastPracticedAt: String? = null
) {
    val isPracticed: Boolean get() = attemptCount > 0
}

data class WeakestLesson(
    val book: String = "nce1",
    val lessonId: Int,
    // P8·2b: 服务端人读标题 (book|lesson 不再裸 id); 空 = 回退裸 id 渲染。
    val label: String = "",
    val bestScore: Double,
    val avgScore: Double,
    val attempts: Int
)

/**
 * 情景课摘要 —— `GET /scenes` 画廊卡片用的轻量视图(计划 §5.3)。
 *
 * 词汇/剧本等大块内容只在 `GET /scenes/{id}` 详情里(P6 才消费), 所以这里
 * 刻意不带它们, 画廊一次拉全也不会变重。
 */
data class SceneSummary(
    val id: String,
    // "curated" = 后端文件里的人工课; "generated" = 本人的 LLM 生成课。
    val source: String = "curated",
    // daily | workplace | exam | travel
    val category: String = "",
    val title: String = "",
    val subtitleEn: String = "",
    // CEFR 目标等级 A1..C2
    val level: String = "",
    val estMinutes: Int = 0,
    val briefCn: String = "",
    val skills: List<String> = emptyList(),
    val vocabCount: Int = 0,
    val briefingCount: Int = 0,
    val taskCount: Int = 0,
    val requiredTaskCount: Int = 0,
    val maxTurns: Int = 0,
    // 通关进度: P4 后端 course_progress 落地前恒为默认值, 所以 UI 必须 false-safe。
    val cleared: Boolean = false,
    val bestTotal: Double = 0.0,
    val attempts: Int = 0
) {
    val isPracticed: Boolean get() = attempts > 0
}

/** 画廊顶部分类 chip: id + 中文名 + 该分类课程数(后端恒给全 4 类)。 */
data class SceneCategoryStat(val id: String, val labelCn: String, val count: Int)

/** `GET /scenes` 的整个载荷。 */
data class SceneCatalog(
    val categories: List<SceneCategoryStat>,
    val scenes: List<SceneSummary>,
    val total: Int,
    val defaultSceneId: String? = null
)
