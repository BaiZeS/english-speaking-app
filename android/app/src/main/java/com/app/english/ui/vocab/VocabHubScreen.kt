package com.app.english.ui.vocab

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CollectionsBookmark
import androidx.compose.material.icons.filled.School
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.ui.components.ActionEntryCard
import com.app.english.ui.components.SectionHeader
import com.app.english.ui.theme.KeliPillShape
import com.app.english.ui.theme.Spacings

/**
 * 词汇 Tab(计划 §6.3 Tab 3): 个人表达库 + 弱词训练两个入口。
 *
 * 表达库入口(P7 真实化)的条数读 `GET /expressions`(Room 快照先行 + 网络校正),
 * 点进 [com.app.english.ui.expressions.ExpressionLibraryScreen]; 弱词训练是 v1 的
 * [com.app.english.ui.drill.MistakeDrillScreen] 原样平移。
 */
@Composable
fun VocabHubScreen(
    onExpressionLibraryClick: () -> Unit,
    onDrillClick: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: VocabHubViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(modifier = modifier) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            SectionHeader(
                title = "词汇",
                subtitle = "把练过的说法攒下来, 下次直接说得出"
            )
            ActionEntryCard(
                title = "表达库",
                subtitle = "对话润色后自动收录",
                icon = Icons.Filled.CollectionsBookmark,
                onClick = onExpressionLibraryClick,
                trailing = state.pendingExpressions?.let { count ->
                    { CounterBadge(count) }
                }
            )
            ActionEntryCard(
                title = "弱词训练",
                subtitle = "专项练习错词与弱词, 逐个攻克",
                icon = Icons.Filled.School,
                onClick = onDrillClick,
                containerColor = MaterialTheme.colorScheme.tertiaryContainer,
                contentColor = MaterialTheme.colorScheme.onTertiaryContainer,
                trailing = if (state.weakWordCount > 0) {
                    { CounterBadge(state.weakWordCount) }
                } else {
                    null
                }
            )
        }
    }
}

@Composable
private fun CounterBadge(count: Int) {
    Surface(shape = KeliPillShape, color = MaterialTheme.colorScheme.secondaryContainer) {
        Text(
            text = count.toString(),
            style = MaterialTheme.typography.labelMedium,
            color = MaterialTheme.colorScheme.onSecondaryContainer,
            modifier = Modifier.padding(horizontal = Spacings.s2, vertical = Spacings.half)
        )
    }
}
