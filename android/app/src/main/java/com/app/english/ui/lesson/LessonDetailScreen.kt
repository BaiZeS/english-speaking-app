package com.app.english.ui.lesson

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import com.app.english.domain.model.LessonDetail
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonDetailScreen(
    onBack: () -> Unit,
    onRoleSelected: (lessonId: Int, roleName: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: LessonDetailViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("选择角色") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        when (val current = state) {
            is LessonDetailUiState.Loading -> LoadingState(Modifier.padding(padding))
            is LessonDetailUiState.Error -> ErrorState(
                message = current.message,
                modifier = Modifier.padding(padding),
                onRetry = viewModel::load
            )

            is LessonDetailUiState.Success -> RoleList(
                lesson = current.lesson,
                onRoleSelected = { roleName -> onRoleSelected(viewModel.lessonId, roleName) },
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun RoleList(
    lesson: LessonDetail,
    onRoleSelected: (roleName: String) -> Unit,
    modifier: Modifier = Modifier
) {
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Text(
                text = lesson.title,
                style = MaterialTheme.typography.titleLarge
            )
        }
        items(lesson.roles, key = { it.name }) { role ->
            Card(
                modifier = Modifier.fillMaxWidth().clickable { onRoleSelected(role.name) }
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(
                        text = "角色 ${role.name}",
                        style = MaterialTheme.typography.titleMedium
                    )
                    Text(
                        text = "${role.lines.size} 句台词",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(top = 4.dp)
                    )
                }
            }
        }
    }
}
