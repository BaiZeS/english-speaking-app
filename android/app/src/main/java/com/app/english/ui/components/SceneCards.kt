package com.app.english.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Card
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.app.english.domain.model.SceneCategoryStat
import com.app.english.domain.model.SceneSummary
import com.app.english.ui.courses.SceneFilter
import com.app.english.ui.theme.SceneCardOnColor
import com.app.english.ui.theme.SceneDailyColor
import com.app.english.ui.theme.SceneExamColor
import com.app.english.ui.theme.SceneTravelColor
import com.app.english.ui.theme.SceneWorkplaceColor
import com.app.english.ui.theme.Spacings

/**
 * 情景课卡片(首页「今日推荐」与课程 Tab 的列表共用一张卡, 差别只在简介行数)。
 *
 * 数据全部来自 `GET /scenes` 的摘要; 通关相关字段(`cleared` / `best_total` /
 * `attempts`)在后端 P4 之前恒为默认值, 所以这里全部按「有就说、没有就不画」处理。
 */
@Composable
fun SceneSummaryCard(
    scene: SceneSummary,
    onClick: (String) -> Unit,
    modifier: Modifier = Modifier,
    briefMaxLines: Int = 2
) {
    Card(modifier = modifier.fillMaxWidth(), onClick = { onClick(scene.id) }) {
        Column(
            modifier = Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
            ) {
                Text(
                    text = scene.title,
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f, fill = false)
                )
                LevelPill(scene.level)
                ClearedBadge(scene.cleared)
            }
            if (scene.subtitleEn.isNotBlank()) {
                Text(
                    text = scene.subtitleEn,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.primary,
                    maxLines = 1
                )
            }
            val summary = SceneFilter.summaryLine(scene)
            if (summary.isNotBlank()) {
                Text(
                    text = summary,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (scene.briefCn.isNotBlank()) {
                Text(
                    text = scene.briefCn,
                    style = MaterialTheme.typography.bodyMedium,
                    maxLines = briefMaxLines
                )
            }
            val skills = SceneFilter.skillPreview(scene)
            if (skills.isNotBlank()) {
                Text(
                    text = skills,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.secondary
                )
            }
            if (scene.isPracticed) {
                Text(
                    text = "练过 ${scene.attempts} 次 · 最高 ${scene.bestTotal.toInt()}",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

/**
 * 场景画廊的彩色分类卡(可栗 2 列网格: 图标 + 标题 + 副标题 + 数量)。
 * 四类的暖色底色见 ui/theme/Color.kt。
 */
@Composable
fun SceneCategoryCard(
    category: SceneCategoryStat,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    val accent = categoryAccent(category.id)
    Card(modifier = modifier, onClick = onClick) {
        Box(modifier = Modifier.fillMaxWidth().padding(Spacings.s1)) {
            Surface(modifier = Modifier.fillMaxSize(), color = accent) {
                Column(
                    modifier = Modifier.fillMaxWidth().padding(Spacings.s2),
                    verticalArrangement = Arrangement.spacedBy(Spacings.s1)
                ) {
                    Text(
                        text = SceneFilter.labelFor(category.id, category.labelCn),
                        style = MaterialTheme.typography.titleMedium,
                        color = SceneCardOnColor,
                        maxLines = 1
                    )
                    Text(
                        text = categorySubtitle(category),
                        style = MaterialTheme.typography.labelSmall,
                        color = SceneCardOnColor,
                        maxLines = 1
                    )
                }
            }
        }
    }
}

private fun categorySubtitle(category: SceneCategoryStat): String =
    if (category.count > 0) "${category.count} 门 · 开始练习" else "内容准备中"

private fun categoryAccent(categoryId: String): Color = when (categoryId) {
    "daily" -> SceneDailyColor
    "workplace" -> SceneWorkplaceColor
    "exam" -> SceneExamColor
    "travel" -> SceneTravelColor
    else -> SceneDailyColor
}

/** 区块内的紧凑进度条, 首页/课程 Tab 的加载分支共用。 */
@Composable
fun InlineLoading(modifier: Modifier = Modifier) {
    Box(
        modifier = modifier.fillMaxWidth().padding(Spacings.s3),
        contentAlignment = Alignment.Center
    ) {
        CircularProgressIndicator(
            modifier = Modifier.size(22.dp),
            color = MaterialTheme.colorScheme.primary
        )
    }
}
