package com.app.english.ui.lessons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.LessonSummary
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonListScreen(
    onLessonClick: (Int) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: LessonListViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("新概念英语 第一册") }) }
    ) { padding ->
        when (val current = state) {
            is LessonListUiState.Loading -> LoadingState(Modifier.padding(padding))
            is LessonListUiState.Error -> ErrorState(
                message = current.message,
                modifier = Modifier.padding(padding),
                onRetry = viewModel::load
            )

            is LessonListUiState.Success -> LessonList(
                lessons = current.lessons,
                onLessonClick = onLessonClick,
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun LessonList(
    lessons: List<LessonSummary>,
    onLessonClick: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(lessons, key = { it.id }) { lesson ->
            LessonRow(lesson = lesson, onClick = { onLessonClick(lesson.id) })
        }
    }
}

@Composable
private fun LessonRow(lesson: LessonSummary, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick)
    ) {
        Column(modifier = Modifier.padding(16.dp)) {
            Text(
                text = "Lesson ${lesson.lessonNo} · ${lesson.title}",
                style = MaterialTheme.typography.titleMedium
            )
            Row(
                modifier = Modifier.padding(top = 6.dp),
                horizontalArrangement = Arrangement.spacedBy(12.dp)
            ) {
                Text(
                    text = "${lesson.roleCount} 个角色",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = "约 ${lesson.durationS.toInt()} 秒",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}
