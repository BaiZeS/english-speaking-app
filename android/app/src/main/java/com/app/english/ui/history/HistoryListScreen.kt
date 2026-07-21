package com.app.english.ui.history

import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.HistoryItem
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.formatScore
import com.app.english.ui.theme.color

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryListScreen(
    onItemClick: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: HistoryListViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("练习历史") }) }
    ) { padding ->
        when (val current = state) {
            is HistoryListUiState.Loading -> LoadingState(Modifier.padding(padding))
            is HistoryListUiState.Error -> ErrorState(
                message = current.message,
                modifier = Modifier.padding(padding),
                onRetry = viewModel::load
            )
            is HistoryListUiState.Success -> {
                if (current.totalCount == 0) {
                    EmptyHistory(Modifier.padding(padding))
                } else {
                    HistoryList(
                        items = current.items,
                        filter = current.filter,
                        totalCount = current.totalCount,
                        onFilterChange = viewModel::setFilter,
                        onClick = { item ->
                            viewModel.select(item)
                            onItemClick()
                        },
                        modifier = Modifier.padding(padding)
                    )
                }
            }
        }
    }
}

@Composable
private fun HistoryList(
    items: List<HistoryItem>,
    filter: HistoryFilter,
    totalCount: Int,
    onFilterChange: (HistoryFilter) -> Unit,
    onClick: (HistoryItem) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(modifier = modifier.fillMaxSize()) {
        FilterBar(
            selected = filter,
            onSelect = onFilterChange,
            totalCount = totalCount,
            shownCount = items.size
        )
        if (items.isEmpty()) {
            Column(
                modifier = Modifier.fillMaxSize().padding(24.dp),
                verticalArrangement = Arrangement.Center,
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                Text(
                    text = "当前筛选下还没有记录",
                    style = MaterialTheme.typography.bodyLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        } else {
            LazyColumn(
                modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
                verticalArrangement = Arrangement.spacedBy(12.dp),
                contentPadding = androidx.compose.foundation.layout.PaddingValues(vertical = 12.dp)
            ) {
                items(items, key = { it.id }) { item ->
                    HistoryRow(item = item, onClick = { onClick(item) })
                }
            }
        }
    }
}

@Composable
private fun FilterBar(
    selected: HistoryFilter,
    onSelect: (HistoryFilter) -> Unit,
    totalCount: Int,
    shownCount: Int
) {
    val scrollState = rememberScrollState()
    Column(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) {
        Text(
            text = "共 $totalCount 次 · 当前显示 $shownCount 条",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(top = 6.dp)
                .horizontalScroll(scrollState),
            horizontalArrangement = Arrangement.spacedBy(8.dp)
        ) {
            HistoryFilter.values().forEach { option ->
                FilterChip(
                    selected = option == selected,
                    onClick = { onSelect(option) },
                    label = { Text(option.label) }
                )
            }
        }
    }
}

@Composable
private fun HistoryRow(item: HistoryItem, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable { onClick() }
    ) {
        Column(Modifier.padding(16.dp)) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(
                        text = "Lesson ${item.lessonId} · ${item.lineId}",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = item.createdAt,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
                Text(
                    text = item.scoreTotal.formatScore(),
                    style = MaterialTheme.typography.titleLarge,
                    color = ScoreColorMapper.level(item.scoreTotal).color()
                )
            }
        }
    }
}

@Composable
private fun EmptyHistory(modifier: Modifier = Modifier) {
    Column(
        modifier = modifier.fillMaxSize().padding(24.dp),
        verticalArrangement = Arrangement.Center,
        horizontalAlignment = Alignment.CenterHorizontally
    ) {
        Text("还没有练习记录", style = MaterialTheme.typography.bodyLarge)
        Text(
            text = "完成第一次跟读或自由对话后，这里会显示你的历史。",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 6.dp)
        )
    }
}
