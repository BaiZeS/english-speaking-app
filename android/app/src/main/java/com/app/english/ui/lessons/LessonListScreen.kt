package com.app.english.ui.lessons

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ArrowDropDown
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.Book
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
        topBar = {
            TopAppBar(
                title = {
                    Text(
                        text = state.selectedBook?.displayName ?: "课文",
                        style = MaterialTheme.typography.titleMedium
                    )
                },
                actions = {
                    if (state.books.size > 1) {
                        BookSelector(
                            books = state.books,
                            selectedId = state.selectedBookId,
                            onSelect = viewModel::selectBook
                        )
                    }
                }
            )
        }
    ) { padding ->
        Column(modifier = Modifier.padding(padding).fillMaxSize()) {
            state.selectedBook?.let { book ->
                if (book.description.isNotBlank()) {
                    BookBanner(
                        book = book,
                        modifier = Modifier.fillMaxWidth().padding(
                            horizontal = 16.dp,
                            vertical = 8.dp
                        )
                    )
                }
            }
            if (state.isLoadingLessons && state.lessons.isEmpty()) {
                LoadingState()
            } else if (state.error != null && state.lessons.isEmpty()) {
                ErrorState(
                    message = state.error ?: "加载失败",
                    onRetry = viewModel::retry
                )
            } else {
                LessonList(
                    lessons = state.lessons,
                    onLessonClick = onLessonClick
                )
            }
        }
    }
}

@Composable
private fun BookBanner(book: Book, modifier: Modifier = Modifier) {
    Card(
        modifier = modifier,
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        )
    ) {
        Column(Modifier.padding(12.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    text = book.displayName,
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Box(Modifier.size(8.dp))
                Surface(
                    shape = RoundedCornerShape(8.dp),
                    color = MaterialTheme.colorScheme.secondaryContainer
                ) {
                    Text(
                        text = "${book.lessonCount} 课",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                        modifier = Modifier.padding(horizontal = 6.dp, vertical = 2.dp)
                    )
                }
            }
            if (book.description.isNotBlank()) {
                Text(
                    text = book.description,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onPrimaryContainer,
                    modifier = Modifier.padding(top = 4.dp)
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun BookSelector(books: List<Book>, selectedId: String, onSelect: (String) -> Unit) {
    var expanded by remember { mutableStateOf(false) }
    val selected = books.firstOrNull { it.id == selectedId }
    Box {
        TextButton(onClick = { expanded = true }) {
            Text(
                text = selected?.displayName ?: "切换课本",
                style = MaterialTheme.typography.labelLarge,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
            Icon(
                Icons.Filled.ArrowDropDown,
                contentDescription = "切换课本",
                modifier = Modifier.size(18.dp)
            )
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { expanded = false }
        ) {
            books.forEach { book ->
                DropdownMenuItem(
                    text = {
                        Column {
                            Text(book.displayName, style = MaterialTheme.typography.bodyLarge)
                            Text(
                                text = "${book.lessonCount} 课 · ${book.level}",
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant
                            )
                        }
                    },
                    onClick = {
                        onSelect(book.id)
                        expanded = false
                    }
                )
            }
        }
    }
}

@Composable
private fun LessonList(lessons: List<LessonSummary>, onLessonClick: (Int) -> Unit) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        items(lessons, key = { it.id }) { lesson ->
            LessonRow(lesson = lesson, onClick = { onLessonClick(lesson.id) })
        }
        if (lessons.isEmpty()) {
            item {
                Box(
                    modifier = Modifier.fillMaxWidth().padding(32.dp),
                    contentAlignment = Alignment.Center
                ) {
                    Text(
                        text = "这本教材还没有课文，敬请期待。",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
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
