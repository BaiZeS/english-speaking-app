package com.app.english.ui.home

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material.icons.filled.Explore
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.SceneCategoryStat
import com.app.english.ui.components.ActionEntryCard
import com.app.english.ui.components.InlineEmptyState
import com.app.english.ui.components.InlineLoading
import com.app.english.ui.components.SceneCategoryCard
import com.app.english.ui.components.SceneSummaryCard
import com.app.english.ui.components.SectionHeader
import com.app.english.ui.components.StreakCard
import com.app.english.ui.theme.Spacings

/**
 * 首页(计划 §6.3 Tab 1): 问候 + 打卡 / 继续学习 / 今日推荐 / 场景画廊 /
 * 生成专属课 / 未测评引导。
 *
 * 两块数据各自独立降级: `GET /stats` 挂了只影响打卡卡, `GET /scenes` 挂了只在
 * 推荐/画廊区块里显示可重试的错误块, 页面不会整体白掉。
 */
@Composable
fun HomeScreen(
    onSceneClick: (sceneId: String) -> Unit,
    onCategoryClick: (categoryId: String) -> Unit,
    onGenerateCourseClick: () -> Unit,
    onAssessmentClick: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: HomeViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(modifier = modifier) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s3)
        ) {
            GreetingHeader(greeting = state.greeting, streakDays = state.streakDays)
            state.stats?.let { stats ->
                StreakCard(
                    streakDays = stats.streakDays,
                    recentSessions = stats.recentSessions
                )
            }
            // TODO(P6): continueLearning 由 GET /courses/progress 点亮; 无数据时整卡隐藏。
            state.continueLearning?.let { target ->
                ActionEntryCard(
                    title = "继续学习",
                    subtitle = target.title,
                    icon = Icons.Filled.School,
                    onClick = { onSceneClick(target.sceneId) }
                )
            }
            TodayPickSection(
                state = state,
                onSceneClick = onSceneClick,
                onRetry = viewModel::refresh
            )
            GallerySection(
                state = state,
                onCategoryClick = onCategoryClick,
                onRetry = viewModel::refresh
            )
            ActionEntryCard(
                title = "生成我的专属课",
                subtitle = "说一句话, AI 给你一节情景课",
                icon = Icons.Filled.AutoAwesome,
                onClick = onGenerateCourseClick,
                containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                contentColor = MaterialTheme.colorScheme.onTertiaryContainer
            )
            // 后端 GET /assessment 之前没有定级数据, 所以引导卡恒显示; P7 有画像后隐藏。
            ActionEntryCard(
                title = "5 分钟测出你的英语水平",
                subtitle = "测评后解锁四维能力画像",
                icon = Icons.Filled.Explore,
                onClick = onAssessmentClick,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun GreetingHeader(greeting: String, streakDays: Int) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
        Text(text = greeting, style = MaterialTheme.typography.headlineMedium)
        Text(
            text = if (streakDays > 0) {
                "已连续 $streakDays 天, 今天也练一会儿"
            } else {
                "今天从一节情景课开始"
            },
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
    }
}

@Composable
private fun TodayPickSection(
    state: HomeUiState,
    onSceneClick: (String) -> Unit,
    onRetry: () -> Unit
) {
    SectionHeader(title = "今日推荐")
    val scene = state.recommended
    when {
        scene != null -> SceneSummaryCard(
            scene = scene,
            onClick = onSceneClick,
            briefMaxLines = BRIEF_LINES_FEATURED
        )
        state.isLoadingScenes -> InlineLoading()
        else -> RetryableBlock(
            message = state.scenesError ?: "暂无情景课, 请稍后再试",
            onRetry = onRetry
        )
    }
}

@Composable
private fun GallerySection(
    state: HomeUiState,
    onCategoryClick: (String) -> Unit,
    onRetry: () -> Unit
) {
    SectionHeader(
        title = "场景画廊",
        subtitle = if (state.sceneTotal > 0) "共 ${state.sceneTotal} 门情景课" else null
    )
    when {
        state.categories.isNotEmpty() -> CategoryGrid(
            categories = state.galleryCategories,
            onCategoryClick = onCategoryClick
        )
        state.isLoadingScenes -> InlineLoading()
        else -> RetryableBlock(
            message = state.scenesError ?: "加载情景课失败",
            onRetry = onRetry
        )
    }
}

/** 两列分类卡网格(不嵌套 LazyGrid, 直接 chunked 成行, 保持整页单滚动容器)。 */
@Composable
private fun CategoryGrid(categories: List<SceneCategoryStat>, onCategoryClick: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s2)) {
        categories.chunked(GALLERY_COLUMNS).forEach { rowItems ->
            Row(horizontalArrangement = Arrangement.spacedBy(Spacings.s2)) {
                rowItems.forEach { category ->
                    SceneCategoryCard(
                        category = category,
                        onClick = { onCategoryClick(category.id) },
                        modifier = Modifier.weight(1f)
                    )
                }
                if (rowItems.size < GALLERY_COLUMNS) {
                    Spacer(Modifier.weight(1f))
                }
            }
        }
    }
}

@Composable
private fun RetryableBlock(message: String, onRetry: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant
        )
    ) {
        Column(modifier = Modifier.padding(Spacings.s2)) {
            InlineEmptyState(text = message)
            TextButton(onClick = onRetry) {
                Text("重试")
            }
        }
    }
}

private const val GALLERY_COLUMNS = 2
private const val BRIEF_LINES_FEATURED = 3
