package com.app.english.ui.courses

import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary

/** 画廊筛选里「全部」这个虚拟分类的 id(不对应后端 category 值)。 */
const val CATEGORY_ALL_ID: String = "all"

/** 顶部分段: 情景课 / 课本(顺序即 Tab 顺序, 计划 §6.3)。 */
enum class CourseSegment(val label: String) {
    SCENES("情景课"),
    TEXTBOOK("课本")
}

/** 一个分类筛选 chip。 */
data class SceneCategoryChip(
    val id: String,
    val label: String,
    val count: Int,
    val isAll: Boolean = false
)

/**
 * 情景课画廊的纯筛选/文案逻辑 —— 没有 Compose 依赖, 所以是普通 JVM 单测
 * (见 `SceneFilterTest`), 界面层只做渲染。
 */
object SceneFilter {
    /**
     * 四个分类的中文名兜底(计划 §6.3)。后端 `label_cn` 永远优先, 这里只在
     * 后端没给/给了空串时顶上, 保证 chip 文案不会退化成裸 id。
     */
    val FALLBACK_LABELS_CN: Map<String, String> = linkedMapOf(
        "daily" to "日常交流",
        "workplace" to "职场商务",
        "exam" to "考试面试",
        "travel" to "旅行出国"
    )

    fun labelFor(categoryId: String, backendLabel: String? = null): String =
        backendLabel?.takeIf { it.isNotBlank() }
            ?: FALLBACK_LABELS_CN[categoryId]
            ?: categoryId

    /** 后端 categories 缺失时也要能画出四张分类卡(count 为 0)。 */
    fun fallbackCategories(): List<SceneCategoryStat> =
        FALLBACK_LABELS_CN.map { (id, label) -> SceneCategoryStat(id, label, 0) }

    /**
     * 分类卡/ chip 用的列表: `全部`(count = 各类之和) + 后端给的每个分类。
     *
     * 后端保证四类和 0 计数的类都会出现(§5.3), 但这里不依赖该保证: 空目录时
     * 兜底补四类, 重复 id 只留第一个, 未知 id 原样排在后面。
     */
    fun chips(categories: List<SceneCategoryStat>): List<SceneCategoryChip> {
        val source = categories.ifEmpty { fallbackCategories() }
        val seen = LinkedHashSet<String>()
        val distinct = source.filter { it.id.isNotBlank() && seen.add(it.id) }
        val all = SceneCategoryChip(
            id = CATEGORY_ALL_ID,
            label = "全部",
            count = distinct.sumOf { it.count },
            isAll = true
        )
        return listOf(all) + distinct.map {
            SceneCategoryChip(id = it.id, label = labelFor(it.id, it.labelCn), count = it.count)
        }
    }

    /**
     * 按分类过滤课程摘要。`null` / 空白 / [CATEGORY_ALL_ID] 都返回全量。
     *
     * 「未知分类」(拼错的 id, 或后端新增而本机兜底表没有的 id)同样返回全量 ——
     * 宁多勿少: 筛选值由后端解释, 客户端不把列表误渲染成「暂无课程」。判定口径:
     * 四个兜底分类或当前目录 [scenes] 里出现过的分类才算认识。
     */
    fun apply(categoryId: String?, scenes: List<SceneSummary>): List<SceneSummary> {
        val key = categoryId?.trim()?.lowercase()?.takeIf { it.isNotEmpty() }
        if (key == null || key == CATEGORY_ALL_ID) return scenes
        val known = FALLBACK_LABELS_CN.containsKey(key) ||
            scenes.any { it.category.lowercase() == key }
        if (!known) return scenes
        return scenes.filter { it.category.lowercase() == key }
    }

    /** 卡片第二行: `B1 · 约 9 分钟 · 4 个任务`。 */
    fun summaryLine(scene: SceneSummary): String = buildString {
        if (scene.level.isNotBlank()) append(scene.level)
        if (scene.estMinutes > 0) {
            if (isNotEmpty()) append(" · ")
            append("约 ${scene.estMinutes} 分钟")
        }
        if (scene.taskCount > 0) {
            if (isNotEmpty()) append(" · ")
            append("${scene.taskCount} 个任务")
        }
    }

    /** 首页分类卡副标题: 用 skills 拼「点餐 · 闲聊 · 电话」那种小词串。 */
    fun skillPreview(scene: SceneSummary, max: Int = 3): String =
        scene.skills.takeIf { it.isNotEmpty() }
            ?.map { it.trim() }?.filter { it.isNotEmpty() }?.take(max)?.joinToString(" · ") ?: ""
}
