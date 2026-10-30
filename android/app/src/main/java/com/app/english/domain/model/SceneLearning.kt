package com.app.english.domain.model

/**
 * 情景课全流程(P6)的领域模型: 课程内容 / 会话快照 / 实战轮 / 复盘报告。
 * 全部由 `data/remote/SessionMappers.kt` 从 DTO 映射, 界面层不接触裸 JSON 字段。
 */

/** 一门情景课的完整内容(`GET /scenes/{id}` 的 `SceneCourse`)。 */
/** 词汇卡: 点击播单词或例句。 */
/** 打基础一步的题目内容(题型决定卡片样式)。 */
/** 参考剧本一对往来(a=AI, b=学员), 复盘页参考剧本直接播。 */
/** 一次 drill 尝试的评分结果。 */
/** 打基础清单里一步的当前位置(渲染进度点 + 重做提示)。 */
/** 任务清单 chip(实战 HUD 顶部横滑)。 */
data class TaskChip(
    val id: String,
    val descCn: String,
    val hintEn: String,
    val required: Boolean,
    val done: Boolean,
    val evidence: String,
    /**
     * 中文提示/要点 (库内早有, T2 起才随视图下发); 空串 = 不渲染那一行。
     * 挨着 [hintEn] 才对, 但它是 add-only 的新键 —— 追加在末尾是为了不动既有调用点
     * (仓内还有按位置构造的用例), 顺序在这里不是语义的一部分。
     */
    val hintCn: String = ""
)

/** 「原句 vs 更好说法」—— 润色气泡 / 复盘对照 / 表达库卡片共用。 */
data class PolishSuggestion(
    val original: String,
    val polished: String,
    val explanationCn: String,
    /** D4 双语: 润色句的中文意思; 空串 = 不渲染那一行。 */
    val polishedCn: String = ""
)

/** 实战对话一轮完成后加进消息列表的条目。 */
/** `GET /sessions/{id}` 恢复快照(同一形状喂给详情/打基础/实战/复盘四页)。 */
/** 恢复页面时按快照重绘的历史轮(不重复打接口)。 */
/** 实战一轮的完整响应(状态机推进 + 收工判定)。 */
/**
 * 「收工」的 202 回执(§P6)。
 *
 * 只有"服务端已经把这局关掉、文案作业已排上"这一件事, 报告本体**不在**这里 ——
 * 那正是收工从 ~68s(最坏 ~125s)掉回亚秒级、不再撞 30s 读超时的原因。
 * 界面拿到它就立刻跳复盘页, 由复盘页轮询 [SessionSnapshot.reviewStatus]。
 */
data class GenerationJob(
    val jobId: String,
    val status: String,
    val progress: Double,
    val stageText: String,
    val sceneId: String?,
    val error: String?,
    /** `course` = 整课生成 | `scene_brief` = 自定义对话场景 (§3 C3; 旧后端缺键 -> course)。 */
    val kind: String = "course"
) {
    val isRunning: Boolean get() = status == "running"
    val isReady: Boolean get() = status == "ready"
    val isFailed: Boolean get() = status == "failed"
}

/** 表达库条目(词汇 Tab / 润色收藏)。 */
