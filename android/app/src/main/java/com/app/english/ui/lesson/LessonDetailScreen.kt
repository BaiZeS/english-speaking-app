package com.app.english.ui.lesson

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.ChatBubbleOutline
import androidx.compose.material.icons.filled.MenuBook
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AssistChipDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
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
import com.app.english.domain.model.LessonDetail
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.player.PlayerMode

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun LessonDetailScreen(
    onBack: () -> Unit,
    onStartPractice: (lessonId: Int, mode: PlayerMode, roleName: String?) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: LessonDetailViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("Practice mode") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "Back")
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

            is LessonDetailUiState.Success -> ModeList(
                lesson = current.lesson,
                onStart = { mode, role -> onStartPractice(viewModel.lessonId, mode, role) },
                modifier = Modifier.padding(padding)
            )
        }
    }
}

@Composable
private fun ModeList(
    lesson: LessonDetail,
    onStart: (PlayerMode, String?) -> Unit,
    modifier: Modifier = Modifier
) {
    val totalLines = lesson.roles.sumOf { it.lines.size }
    LazyColumn(
        modifier = modifier.fillMaxSize().padding(16.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp)
    ) {
        item {
            Column {
                Text(
                    text = "Lesson ${lesson.lessonNo}",
                    style = MaterialTheme.typography.labelLarge,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Text(
                    text = lesson.title,
                    style = MaterialTheme.typography.headlineSmall
                )
            }
        }
        item {
            ReadAlongCard(
                totalLines = totalLines,
                onClick = { onStart(PlayerMode.READ_ALONG, null) }
            )
        }
        item {
            DialogueCard(
                lesson = lesson,
                onPickRole = { role -> onStart(PlayerMode.DIALOGUE, role) }
            )
        }
    }
}

@Composable
private fun ReadAlongCard(totalLines: Int, onClick: () -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth().clickable(onClick = onClick),
        colors = CardDefaults.cardColors(
            containerColor = MaterialTheme.colorScheme.primaryContainer
        ),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.MenuBook,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onPrimaryContainer
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Read along",
                    style = MaterialTheme.typography.titleLarge,
                    color = MaterialTheme.colorScheme.onPrimaryContainer
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Read every line in order, no role split.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onPrimaryContainer
            )
            Spacer(Modifier.height(12.dp))
            AssistChip(
                onClick = onClick,
                label = { Text("$totalLines lines") },
                colors = AssistChipDefaults.assistChipColors(
                    containerColor = MaterialTheme.colorScheme.surface
                )
            )
        }
    }
}

@Composable
private fun DialogueCard(lesson: LessonDetail, onPickRole: (String) -> Unit) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        shape = RoundedCornerShape(12.dp)
    ) {
        Column(modifier = Modifier.padding(20.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Icon(
                    Icons.Filled.ChatBubbleOutline,
                    contentDescription = null,
                    tint = MaterialTheme.colorScheme.onSurface
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    text = "Dialogue",
                    style = MaterialTheme.typography.titleLarge
                )
            }
            Spacer(Modifier.height(8.dp))
            Text(
                text = "Pick a role and follow its lines.",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Spacer(Modifier.height(12.dp))
            // One row of role chips; tap to enter. Wraps when many roles.
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                lesson.roles.forEach { role ->
                    OutlinedButton(onClick = { onPickRole(role.name) }) {
                        Text("Role ${role.name} - ${role.lines.size} lines")
                    }
                }
            }
        }
    }
}
