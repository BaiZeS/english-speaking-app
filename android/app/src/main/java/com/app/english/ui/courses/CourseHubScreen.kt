package com.app.english.ui.courses

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.SceneSummary
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.InlineEmptyState
import com.app.english.ui.components.InlineLoading
import com.app.english.ui.components.SceneSummaryCard
import com.app.english.ui.components.SegmentedTabs
import com.app.english.ui.lessons.LessonListScreen
import com.app.english.ui.theme.KeliPillShape
import com.app.english.ui.theme.Spacings

/**
 * 课程 Tab(计划 §6.3 Tab 2): 顶部分段「情景课 / 课本」。
 *
 * 课本分支直接嵌 v1 的 [LessonListScreen], 内部逻辑零改动; 情景课分支是新的
 * `GET /scenes` 画廊, 点击进 P6 的详情页。
 *
 * @param initialCategory 首页分类卡带过来的筛选(由 AppNavHost 暂存, 消费后回调清空)。
 */
@Composable
fun CourseHubScreen(
    onSceneClick: (sceneId: String) -> Unit,
    onLessonClick: (book: String, lessonId: Int) -> Unit,
    modifier: Modifier = Modifier,
    initialCategory: String? = null,
    onCategoryConsumed: () -> Unit = {},
    viewModel: CourseHubViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(initialCategory) {
        initialCategory?.takeIf { it.isNotBlank() }?.let { category ->
            viewModel.selectCategory(category)
            onCategoryConsumed()
        }
    }
    Scaffold(modifier = modifier) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .padding(horizontal = Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            SegmentedTabs(
                options = CourseSegment.entries.map { it.label },
                selectedIndex = CourseSegment.entries.indexOf(state.segment),
                onSelect = { index ->
                    CourseSegment.entries.getOrNull(index)?.let(viewModel::selectSegment)
                },
                modifier = Modifier.fillMaxWidth().padding(top = Spacings.s2)
            )
            when (state.segment) {
                CourseSegment.SCENES -> SceneSection(
                    state = state,
                    onSceneClick = onSceneClick,
                    onSelectCategory = viewModel::selectCategory,
                    onRetry = viewModel::retry
                )
                // 旧课本列表原样平移(自带顶栏: 书名 + 选课器)。
                CourseSegment.TEXTBOOK -> LessonListScreen(
                    onLessonClick = onLessonClick,
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}

@Composable
private fun SceneSection(
    state: CourseHubUiState,
    onSceneClick: (String) -> Unit,
    onSelectCategory: (String) -> Unit,
    onRetry: () -> Unit
) {
    CategoryChips(
        chips = state.chips,
        selectedId = state.selectedCategory,
        onSelect = onSelectCategory,
        visible = state.hasScenes || state.categories.isNotEmpty()
    )
    when {
        state.isLoading && !state.hasScenes -> InlineLoading()
        state.error != null && !state.hasScenes -> ErrorState(
            message = state.error ?: "加载情景课失败",
            onRetry = onRetry
        )
        else -> SceneList(
            scenes = state.visibleScenes,
            onSceneClick = onSceneClick
        )
    }
}

@Composable
private fun SceneList(
    scenes: List<com.app.english.domain.model.SceneSummary>,
    onSceneClick: (String) -> Unit
) {
    if (scenes.isEmpty()) {
        InlineEmptyState(text = "这个分类下还没有情景课, 换一个试试")
        return
    }
    LazyColumn(
        modifier = Modifier.fillMaxSize(),
        verticalArrangement = Arrangement.spacedBy(Spacings.s2)
    ) {
        items(scenes, key = { it.id }) { scene ->
            SceneSummaryCard(scene = scene, onClick = onSceneClick)
        }
        // 列表末尾留一格, 最后一张卡不会被底部栏压住
        item(key = "list-bottom-spacer") { Spacer(Modifier.height(Spacings.s3)) }
    }
}

/** 分类筛选 chip 行: 「全部」+ 四类, 选中用主色实心(可栗的暖棕 chips)。 */
@Composable
private fun CategoryChips(
    chips: List<SceneCategoryChip>,
    selectedId: String,
    onSelect: (String) -> Unit,
    visible: Boolean
) {
    if (!visible) return
    Row(
        modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        chips.forEach { chip ->
            Chip(
                label = if (chip.isAll) chip.label else "${chip.label} ${chip.count}",
                selected = chip.id == selectedId,
                onClick = { onSelect(chip.id) }
            )
        }
    }
}

@Composable
private fun Chip(label: String, selected: Boolean, onClick: () -> Unit) {
    Surface(
        shape = KeliPillShape,
        color = if (selected) {
            MaterialTheme.colorScheme.primary
        } else {
            MaterialTheme.colorScheme.surfaceVariant
        }
    ) {
        Text(
            text = label,
            style = MaterialTheme.typography.labelLarge,
            color = if (selected) {
                MaterialTheme.colorScheme.onPrimary
            } else {
                MaterialTheme.colorScheme.onSurfaceVariant
            },
            modifier = Modifier
                .clickable(onClick = onClick)
                .padding(horizontal = Spacings.s3, vertical = Spacings.s1)
        )
    }
}
