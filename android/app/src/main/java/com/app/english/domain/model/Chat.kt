package com.app.english.domain.model

/**
 * v3.0 微信式情景对话的领域模型 —— 对应 `backend/app/api/v1/dialogue_threads.py`。
 *
 * 一条会话就是**一串气泡**, 四种 `kind` 在同一条流里: 角色台词、我那句、建议回答、
 * 评分卡。评分回填不另开数据面, 只是把同一颗 [ChatBubbleKind.GRADE] 从 pending 重绘
 * 成 ready —— 所以渲染层必须能画"一颗还没有内容的评分卡"。
 */
data class ChatThread(
    val id: String,
    val sceneId: String,
    val turnCount: Int = 0,
    val gradingStatus: String = "",
    val beatIndex: Int = 0,
    val messages: List<ChatMessage> = emptyList()
)

/** 会话列表的一行 (头像与标题由 UI 拿场景目录按 `sceneId` join)。 */
data class ThreadSummary(
    val id: String,
    val sceneId: String,
    val preview: String = "",
    val lastAt: String = "",
    val turnCount: Int = 0,
    val unread: Int = 0,
    val gradingStatus: String = ""
)

data class ChatMessage(
    /** 单调且唯一, 直接当 LazyColumn 的 key。 */
    val id: String,
    val kind: String,
    val roleId: String = "",
    val text: String = "",
    val textCn: String = "",
    val audioUrl: String? = null,
    val audioMs: Long = 0,
    /** true = 后端请求内没合成出来; 客户端按需 `GET /tts` 兜底, **不是错误**。 */
    val audioPending: Boolean = false,
    /** 学员这句是中文还是英文 (服务端从转写文本判, 不是学员声明的)。 */
    val spoke: String = "",
    val recognizedText: String = "",
    val localRecording: String = "",
    val grade: ChatGrade? = null
) {
    /** 语音条形态: 角色台词与"我说的话"都可能是语音; 建议/评分永远是文本。 */
    val isVoiceBubble: Boolean
        get() = kind == ChatBubbleKind.LINE ||
            (kind == ChatBubbleKind.USER && localRecording.isNotBlank())
}

/**
 * 一轮的评分。
 *
 * [axes] 缺一个 key = 这一轮**没有那个维度的证据**, 整行不渲染。尤其 `pronunciation`:
 * 说中文或打字的那一轮根本没测发音, 画 0 分等于把"没测"说成"测了且很差"。
 */
data class ChatGrade(
    val status: String = "",
    val score: Int = 0,
    val axes: Map<String, Double> = emptyMap(),
    val comment: String = "",
    val commentCn: String = ""
) {
    val isPending: Boolean get() = status == GRADE_PENDING
    val isReady: Boolean get() = status == GRADE_READY
    val isFailed: Boolean get() = status == GRADE_FAILED

    companion object {
        const val GRADE_PENDING = "pending"
        const val GRADE_READY = "ready"
        const val GRADE_FAILED = "failed"

        /** 评分卡上四个轴的中文标签 (缺轴 = 这一行不出现)。 */
        val AXIS_LABELS_CN = linkedMapOf(
            "relevance" to "切题",
            "informativeness" to "信息",
            "appropriateness" to "得体",
            "beat_progress" to "推进",
            "pronunciation" to "发音"
        )
    }
}

/** 一条消息流里的四种气泡。 */
object ChatBubbleKind {
    const val LINE = "line"
    const val HINT = "hint"
    const val GRADE = "grade"
    const val USER = "user"
}
