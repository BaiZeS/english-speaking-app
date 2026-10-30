package com.app.english.ui.chat

import com.app.english.domain.model.ChatBubbleKind
import com.app.english.domain.model.ChatGrade
import com.app.english.domain.model.ChatMessage

/**
 * 聊天界面的**纯逻辑** —— 渲染决策全部收在这里, 好让它们能被 JVM 单测钉住。
 *
 * 本仓没有 Compose UI 测试底座, 所以「点语音条出文字」「缺轴不渲染」「有 pending 无 url
 * 不许报错」这类契约如果写在 composable 里, 就只能靠真机走查发现 —— 而真机走查恰恰是
 * 这个盒子上永远排不上的那件事。
 */

// 语音条的时长换算与波形密度。这些数字是"微信长这样"的一部分, 写成字面量会让下一个
// 人不知道该不该动。
private const val HALF_SECOND_MS = 500L
private const val SECOND_MS = 1000L
private const val MINUTE_SECONDS = 60
private const val BARS_PER_SECOND = 2
private const val MIN_BARS = 3
private const val MAX_BARS = 14

/** 语音条上显示的时长: 微信用「N″」这种短形, 超过一分钟才换成分秒。 */
fun voiceBarLabel(audioMs: Long): String {
    if (audioMs <= 0L) return ""
    val seconds = ((audioMs + HALF_SECOND_MS) / SECOND_MS).toInt()
    return if (seconds < MINUTE_SECONDS) {
        "$seconds″"
    } else {
        "%d:%02d".format(seconds / MINUTE_SECONDS, seconds % MINUTE_SECONDS)
    }
}

/** 语音条该画几根波形: 按时长给个微信式的密度, 不随音频内容变 (没有解码波形这回事)。 */
fun voiceBarBars(audioMs: Long): Int {
    if (audioMs <= 0L) return MIN_BARS
    val seconds = ((audioMs + HALF_SECOND_MS) / SECOND_MS).toInt()
    return (seconds * BARS_PER_SECOND).coerceIn(MIN_BARS, MAX_BARS)
}

/**
 * 长按气泡时的翻译动作。
 *
 * **自带双语的气泡绝不发网络请求** —— 台词与建议句在生成时就带了 `text`/`text_cn`
 * 成对字段, 再调一次 LLM 是把已有的东西重新算一遍, 还要学员多等 1~3 秒。
 * 只有没有对照的文本 (典型是学员自己那句中文) 才走 `/translate`。
 */
sealed class TranslationPlan {
    /** 本地切换到目标语言: 数据已经在消息里。 */
    data class LocalToggle(val targetLang: String) : TranslationPlan()

    /** 真调翻译端点。 */
    data class Remote(val text: String, val targetLang: String) : TranslationPlan()

    /** 这一条没什么可翻的 (空文本, 或只有一种语言且无法确定方向)。 */
    data object Nothing : TranslationPlan()
}

const val LANG_ZH = "zh"
const val LANG_EN = "en"

// 汉字码位区间 (中日韩统一表意文字基本区)。只用来判"这句里有没有中文", 不做完整分词。
private val HAN_RANGES: List<IntRange> = listOf(0x4E00..0x9FFF, 0x3400..0x4DBF, 0xF900..0xFAFF)

/**
 * [showingCn] 是**界面自己携带的展示态** (哪些气泡已经展开中文), 不是后端字段 ——
 * 服务端从不返回它。放在 UI 层而不是塞回 domain model: 后端加字段会进 DTO 契约,
 * 而"这一条此刻给人看的是哪一版"是设备上的临时状态, 换设备/重开根本不该同步。
 */
fun translationPlan(message: ChatMessage, showingCn: Boolean = false): TranslationPlan {
    // 「我」那句: 原文是学员的话, 对照要现翻。方向按学员说的语言取反。
    if (message.kind == ChatBubbleKind.USER) {
        val source = message.recognizedText.ifBlank { message.text }
        if (source.isBlank()) return TranslationPlan.Nothing
        return TranslationPlan.Remote(source, if (containsHan(source)) LANG_EN else LANG_ZH)
    }
    if (message.kind == ChatBubbleKind.HINT || message.kind == ChatBubbleKind.LINE) {
        val hasEn = message.text.isNotBlank()
        val hasCn = message.textCn.isNotBlank()
        return when {
            hasEn && hasCn -> TranslationPlan.LocalToggle(if (showingCn) LANG_EN else LANG_ZH)
            hasEn -> TranslationPlan.Remote(message.text, LANG_ZH)
            hasCn -> TranslationPlan.Remote(message.textCn, LANG_EN)
            else -> TranslationPlan.Nothing
        }
    }
    return TranslationPlan.Nothing
}

fun containsHan(text: String): Boolean = text.any { ch -> HAN_RANGES.any { ch.code in it } }

/**
 * 语音条有没有音频可播。
 *
 * `audioPending` 且没有 URL 是**正常降级** (后端请求内合成只给 3s 预算), 不是错误:
 * 返回 false 让界面去按需补合成, 补不到就只显示文字。任何把它当失败弹提示的路径都不许出现。
 */
fun hasPlayableAudio(message: ChatMessage): Boolean = message.audioUrl != null

/** 需要客户端按需 `GET /tts` 补一条音频。 */
fun needsTtsFallback(message: ChatMessage): Boolean = message.kind == ChatBubbleKind.LINE &&
    message.audioUrl == null &&
    message.audioPending &&
    message.text.isNotBlank()

/**
 * 评分卡的渲染计划。
 *
 * **缺一个轴就不画那一行** —— 尤其 `pronunciation`: 学员说中文或打字的那一轮根本没测发音,
 * 画 0 分等于把"没测"说成"测了且很差"。`failed` 整颗气泡不渲染 (点评没有, 但**这一轮
 * 存在**, 所以其它气泡一颗都不能少)。
 */
data class GradeRender(
    val visible: Boolean,
    val pending: Boolean,
    val scoreLabel: String,
    val axes: List<Pair<String, Int>>,
    val comment: String
)

fun gradeRender(grade: ChatGrade?): GradeRender {
    if (grade == null) return GradeRender(false, false, "", emptyList(), "")
    if (grade.isFailed) return GradeRender(false, false, "", emptyList(), "")
    if (grade.isPending) return GradeRender(true, true, "", emptyList(), "")
    val axes = ChatGrade.AXIS_LABELS_CN.entries
        .filter { (key, _) -> grade.axes.containsKey(key) }
        .map { (key, label) -> label to grade.axes.getValue(key).toInt() }
    return GradeRender(
        visible = true,
        pending = false,
        scoreLabel = grade.score.toString(),
        axes = axes,
        comment = grade.commentCn.ifBlank { grade.comment }
    )
}

/**
 * 合并一轮新增的气泡。
 *
 * 后端 [TurnResult.appended] 是**增量**, 整条替换会把"提交失败时保留用户那颗气泡"的
 * 乐观显示冲掉; 而按 id 去重是必须的 —— 回填轮询会把同一颗评分卡再送一次 (状态已从
 * pending 变成 ready), 不去重就会每轮长出第二颗评分卡。
 */
fun mergeAppended(existing: List<ChatMessage>, appended: List<ChatMessage>): List<ChatMessage> {
    val seen = existing.mapTo(HashSet()) { it.id }
    return existing + appended.filterNot { it.id in seen }
}

/** 整份重读时的合并: 同 id 用服务端那份覆盖 (评分回填就是靠这个翻转的)。 */
fun mergeSnapshot(existing: List<ChatMessage>, snapshot: List<ChatMessage>): List<ChatMessage> {
    if (snapshot.isEmpty()) return existing
    val byId = snapshot.associateBy { it.id }
    val kept = existing.map { byId[it.id] ?: it }
    val seen = kept.mapTo(HashSet()) { it.id }
    return kept + snapshot.filterNot { it.id in seen }
}

/** 只要还有任何一颗评分卡在 pending, 就继续轮询回填。 */
fun anyGradePending(messages: List<ChatMessage>): Boolean =
    messages.any { it.kind == ChatBubbleKind.GRADE && it.grade?.isPending == true }

/**
 * 气泡的列表 key。
 *
 * v2.3.0 那次实战页用**内容**当 key, 撞了重复 key 崩溃 (`6fae05d`): 失败也落气泡、
 * 同一句台词被两个角色说、回填把一颗气泡改回原样, 都会造出内容相等的两行。
 * 服务端保证 `id` 单调唯一, 所以 key 只能用它。
 */
fun bubbleKey(message: ChatMessage): String = message.id

/**
 * 评分回填的轮询节奏 —— 与已退役的实战页判分轮询同一判据, 搬进本包是因为那个文件随
 * 实战页一起删了, 而"pending 才轮、失败不中断、连续失败到上限就停"这套纪律不能丢。
 */
object GradingPollCadence {
    const val FAST_MILLIS = 1_500L
    const val MAX_MILLIS = 6_000L
    const val MAX_FAILURES = 5

    /** 还在等的态: pending 要轮; failed **也**继续轮 —— 过一轮水位它还能翻成 ready。 */
    fun shouldKeepPolling(status: String): Boolean =
        status == ChatGrade.GRADE_PENDING || status == ChatGrade.GRADE_FAILED

    fun nextDelayMillis(current: Long): Long = (current * 2).coerceAtMost(MAX_MILLIS)

    fun shouldGiveUp(consecutiveFailures: Int): Boolean = consecutiveFailures >= MAX_FAILURES
}

/**
 * 学员自己那句的本机回放 URI。
 *
 * 服务端**不存学员音频** (只存听写文本), 所以语音气泡回听必须走本地文件。后端在
 * `localRecording` 里回显的只是文件名, 而界面拿不到 Android 的 filesDir —— 所以
 * 保存那一刻就把 `name -> file:// URI` 记在 [taken] 里 (由 ViewModel 持有), 这里只做查表。
 * 查不到就不播; 绝不允许退回去用 TTS 合成一段冒充"你刚才说的话"。
 */
fun localRecordingPath(message: ChatMessage, taken: Map<String, String>): String? =
    message.localRecording.takeIf { it.isNotBlank() }?.let { taken[it] }
