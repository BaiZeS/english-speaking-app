package com.app.english.ui.score

import com.app.english.domain.model.WordScore
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.Json

/**
 * 成绩会话的**纯**编解码(无 Android 依赖, JVM 往返可测)。
 *
 * 落盘这件事只需要一个 JSON 文件, 但"能不能还原"必须能在 JVM 上被证明 —— 所以序列化
 * 形状与 IO 分开放: 这里只负责 [encode]/[decode], 文件读写在 [ScoreSessionStore]。
 *
 * 为什么要持久化: 成绩页([ScoreResultScreen])读的是客户端内存聚合, 里面既有逐词分
 * 又有 LLM 建议 —— 后端 `history` 表每行只存 total/pronunciation/fluency/completeness
 * 四个数, 重建不出这张页(`backend/app/models/db.py` 的 History)。所以只能本地留一份。
 *
 * 解码失败一律返回 null 而不是抛: 缓存坏了的正确行为是"没有缓存", 不是崩溃。
 */
object ScoreSessionCodec {
    private val json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = true
    }

    fun encode(session: ScoreSession): String =
        json.encodeToString(PersistedScoreSession.serializer(), session.toPersisted())

    fun decode(text: String?): ScoreSession? {
        val payload = text?.takeIf { it.isNotBlank() } ?: return null
        return runCatching { json.decodeFromString(PersistedScoreSession.serializer(), payload) }
            .getOrNull()
            ?.toDomain()
    }
}

@Serializable
internal data class PersistedWordScore(
    val word: String = "",
    val score: Double = 0.0,
    val ipa: String? = null
)

@Serializable
internal data class PersistedLineResult(
    val lineId: String = "",
    val text: String = "",
    val total: Double = 0.0,
    val wordScores: List<PersistedWordScore> = emptyList()
)

@Serializable
internal data class PersistedScoreSession(
    val lessonTitle: String = "",
    val roleName: String = "",
    val totalScore: Double = 0.0,
    val pronunciation: Double = 0.0,
    val fluency: Double = 0.0,
    val completeness: Double = 0.0,
    val suggestion: String? = null,
    val lineCount: Int = 0,
    val lineResults: List<PersistedLineResult> = emptyList(),
    // "xunfei"=真实评测, 其它=占位假分。丢了它, 重启后成绩页就不挂警示了。
    val source: String = "stub"
)

private fun ScoreSession.toPersisted() = PersistedScoreSession(
    lessonTitle = lessonTitle,
    roleName = roleName,
    totalScore = totalScore,
    pronunciation = pronunciation,
    fluency = fluency,
    completeness = completeness,
    suggestion = suggestion,
    lineCount = lineCount,
    lineResults = lineResults.map { line ->
        PersistedLineResult(
            lineId = line.lineId,
            text = line.text,
            total = line.total,
            wordScores = line.wordScores.map {
                PersistedWordScore(word = it.word, score = it.score, ipa = it.ipa)
            }
        )
    },
    source = source
)

private fun PersistedScoreSession.toDomain() = ScoreSession(
    lessonTitle = lessonTitle,
    roleName = roleName,
    totalScore = totalScore,
    pronunciation = pronunciation,
    fluency = fluency,
    completeness = completeness,
    suggestion = suggestion,
    lineCount = lineCount,
    lineResults = lineResults.map { line ->
        LineScoreResult(
            lineId = line.lineId,
            text = line.text,
            total = line.total,
            wordScores = line.wordScores.map { WordScore(it.word, it.score, it.ipa) }
        )
    },
    source = source
)
