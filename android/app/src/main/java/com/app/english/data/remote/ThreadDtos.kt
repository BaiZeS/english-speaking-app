package com.app.english.data.remote

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable

/**
 * v3.0 微信式会话线程的 DTO —— 形状对应 `backend/app/api/v1/dialogue_threads.py`。
 *
 * `doc.messages` 是**客户端渲染的唯一真相**: 角色台词、我那句、建议回答、评分卡是
 * 同一条消息流里的四种气泡 (`kind`), 所以评分回填不需要第二条数据面 —— 回填只是把
 * 同一颗气泡从 pending 重绘成 ready。
 *
 * 全部字段带默认值 + `ignoreUnknownKeys`: 后端加字段不许让存量包解析崩。
 */
@Serializable
data class ThreadViewDto(
    val id: String = "",
    @SerialName("scene_id") val sceneId: String = "",
    @SerialName("turn_count") val turnCount: Int = 0,
    @SerialName("grading_status") val gradingStatus: String = "",
    @SerialName("beat_index") val beatIndex: Int = 0,
    val messages: List<ThreadMessageDto> = emptyList()
)

@Serializable
data class ThreadMessageDto(
    /** 单调且唯一 —— 直接当 LazyColumn 的 key。v2.3.0 用内容当 key 崩过一次 (6fae05d)。 */
    val id: String = "",
    /** line | hint | grade | user */
    val kind: String = "",
    @SerialName("role_id") val roleId: String = "",
    val text: String = "",
    @SerialName("text_cn") val textCn: String = "",
    @SerialName("audio_url") val audioUrl: String? = null,
    @SerialName("audio_ms") val audioMs: Long = 0,
    /** true = 后端请求内没合成出来; 客户端按需 `GET /tts` 兜底, 不许当错误显示。 */
    @SerialName("audio_pending") val audioPending: Boolean = false,
    /** 学员这句是中文还是英文 —— 服务端从转写文本判的, 不是学员声明的。 */
    val spoke: String = "",
    @SerialName("recognized_text") val recognizedText: String = "",
    /** 本机录音文件名; 服务端不存学员音频, 回放走本地。 */
    @SerialName("local_recording") val localRecording: String = "",
    val beat: String = "",
    val grade: ThreadGradeDto? = null,
    val at: String = ""
)

@Serializable
data class ThreadGradeDto(
    /** "" | pending | ready | failed */
    val status: String = "",
    val score: Int = 0,
    /**
     * 缺一个 key = 这一轮**没有那个维度的证据**, 整行不渲染。
     * 尤其 `pronunciation`: 说中文/打字的那一轮根本没测发音, 画 0 分等于说"测了且很差"。
     */
    val axes: Map<String, Double> = emptyMap(),
    val comment: String = "",
    @SerialName("comment_cn") val commentCn: String = ""
)

/** 会话列表的一行; 头像与标题由客户端拿 [DialogueSceneDto] 目录按 `scene_id` join。 */
@Serializable
data class ThreadSummaryDto(
    val id: String = "",
    @SerialName("scene_id") val sceneId: String = "",
    val preview: String = "",
    @SerialName("last_at") val lastAt: String = "",
    @SerialName("turn_count") val turnCount: Int = 0,
    val unread: Int = 0,
    @SerialName("grading_status") val gradingStatus: String = ""
)

@Serializable
data class ThreadCreateRequestDto(
    @SerialName("scene_key") val sceneKey: String
)

@Serializable
data class ThreadDeletedDto(
    val deleted: Boolean = true,
    val id: String = ""
)

/**
 * 一轮的入参: 语音或文字二选一。
 *
 * **没有 `lang` 字段** —— 语音一律走讯飞 `zh_cn` 中英混读听写 (实测英文音频的转写质量
 * 与 `en_us` 实质等价), 学员说了哪种语言由服务端从转写文本事后判, 判出来只决定要不要
 * 跑英文逐词发音分。让学员开口前先声明语言, 是把系统能自己做的事推给用户。
 */
@Serializable
data class ThreadTurnRequestDto(
    /** "voice" | "text" */
    val mode: String,
    @SerialName("audio_b64") val audioB64: String = "",
    val text: String = "",
    @SerialName("recording_ref") val recordingRef: String = "",
    @SerialName("model_id") val modelId: String? = null
)

@Serializable
data class ThreadTurnResponseDto(
    @SerialName("thread_id") val threadId: String = "",
    @SerialName("turn_count") val turnCount: Int = 0,
    @SerialName("grading_status") val gradingStatus: String = "",
    @SerialName("beat_index") val beatIndex: Int = 0,
    /** 本轮新增的气泡, 顺序即上屏顺序 (学员那句 -> 台词 -> 建议 -> 评分占位)。 */
    val messages: List<ThreadMessageDto> = emptyList()
)

/** `POST /translate` —— 只服务没有现成双语的那条消息 (有对照的本地切, 不发请求)。 */
@Serializable
data class TranslateRequestDto(
    val text: String,
    @SerialName("target_lang") val targetLang: String
)

@Serializable
data class TranslateResponseDto(
    val translated: String = "",
    /** 恒 "llm": 翻不出来是 503, 没有"降级翻译"这一档。 */
    val source: String = "llm"
)
