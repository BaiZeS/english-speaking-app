package com.app.english.ui.score

import com.app.english.domain.model.WordScore
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Aggregate result of a completed read-along session, passed from the player
 * to the score-result screen via this singleton holder (avoids passing complex
 * objects through nav args).
 */
data class ScoreSession(
    val lessonTitle: String,
    val roleName: String,
    val totalScore: Double,
    val pronunciation: Double,
    val fluency: Double,
    val completeness: Double,
    val suggestion: String?,
    val lineCount: Int,
    val lineResults: List<LineScoreResult>,
    // "xunfei"=真实评测, 其它=占位假分. 成绩页据此显示警示.
    val source: String = "stub"
) {
    val isStub: Boolean get() = source != "xunfei"
}

data class LineScoreResult(
    val lineId: String,
    val text: String,
    val total: Double,
    val wordScores: List<WordScore>
)

/**
 * 读写都转发给 [ScoreSessionStore]：进程被杀之后成绩页仍然还原得出来(E5)。以前这里是
 * 一个裸 `var`，于是它是全部评分面里唯一"杀进程即丢"的那一个 —— 其余各页要么有服务端
 * 快照，要么有本地留档。
 *
 * 转发而不是改造调用点：四处写入方(播读 / 影子跟读 / 自由对话)本来就只把它当"一个能跨页
 * 的槽位"用，语义没变，只是这个槽位现在会掉到磁盘上再爬回来。
 */
@Singleton
class ScoreSessionHolder @Inject constructor(private val store: ScoreSessionStore) {
    var session: ScoreSession?
        get() = store.session
        set(value) {
            store.session = value
        }

    /** 新一轮练习开始前调用：上一局的残档不该在这一局结束后冒充这一局的成绩。 */
    fun clear() = store.clear()
}
