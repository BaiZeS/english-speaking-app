package com.app.english.ui.expressions

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Delete
import androidx.compose.material.icons.filled.VolumeUp
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Card
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextDecoration
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ExpressionEntry
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.InlineEmptyState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.theme.Spacings

/**
 * 个人表达库(计划 §6.4/§5.7): 润色句大字 + 原句删除线 + 解释 + 来源 chip +
 * 播放/删除; 右上角「+」对任意一句 POST /polish 并收进库。
 */

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ExpressionLibraryScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: ExpressionLibraryViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    var showPolishDialog by remember { mutableStateOf(false) }

    LaunchedEffect(state.snackbar) {
        state.snackbar?.let {
            snackbarHostState.showSnackbar(it)
            viewModel.consumeSnackbar()
        }
    }

    Scaffold(
        modifier = modifier,
        snackbarHost = { SnackbarHost(snackbarHostState) },
        topBar = {
            TopAppBar(
                title = { Text("表达库") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                },
                actions = {
                    IconButton(onClick = { showPolishDialog = true }) {
                        Icon(Icons.Filled.Add, contentDescription = "润色一句并收藏")
                    }
                }
            )
        }
    ) { padding ->
        when {
            state.isLoading -> LoadingState(modifier = Modifier.padding(padding))

            state.error != null && state.entries.isEmpty() -> ErrorState(
                message = state.error ?: "加载表达库失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::refresh
            )

            state.entries.isEmpty() -> Column(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
                    .padding(Spacings.s4),
                verticalArrangement = Arrangement.Center
            ) {
                InlineEmptyState(
                    text = "还没有收藏的说法。自由对话与实战里被润色过的好句子会自动收进来; " +
                        "也可以点右上角 + 润色任意一句。"
                )
            }

            else -> LazyColumn(
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
                    .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
                verticalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                if (state.fromCache) {
                    item(key = "offline-hint") {
                        Text(
                            text = "离线中, 显示最近一次缓存",
                            style = MaterialTheme.typography.labelSmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                items(state.entries, key = { it.id }) { entry ->
                    ExpressionCard(
                        entry = entry,
                        onPlay = { viewModel.play(entry) },
                        onDelete = { viewModel.delete(entry) }
                    )
                }
            }
        }
    }

    if (showPolishDialog) {
        PolishDialog(
            isPolishing = state.isPolishing,
            onDismiss = { showPolishDialog = false },
            onConfirm = { text ->
                showPolishDialog = false
                viewModel.polishAndCollect(text)
            }
        )
    }
}

@Composable
private fun ExpressionCard(entry: ExpressionEntry, onPlay: () -> Unit, onDelete: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Text(
                text = entry.polished,
                style = MaterialTheme.typography.titleMedium
            )
            val originalDifferent = entry.original.isNotBlank() && entry.original != entry.polished
            if (originalDifferent) {
                Text(
                    text = entry.original,
                    style = MaterialTheme.typography.bodySmall,
                    textDecoration = TextDecoration.LineThrough,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (entry.explanationCn.isNotBlank()) {
                Text(
                    text = entry.explanationCn,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Surface(
                    shape = RoundedCornerShape(50),
                    color = MaterialTheme.colorScheme.secondaryContainer
                ) {
                    Text(
                        text = sourceLabelCn(entry.sourceLabel),
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                        modifier = Modifier.padding(
                            horizontal = Spacings.s2,
                            vertical = Spacings.half
                        )
                    )
                }
                Row(modifier = Modifier.weight(1f), horizontalArrangement = Arrangement.End) {
                    IconButton(onClick = onPlay) {
                        Icon(Icons.Filled.VolumeUp, contentDescription = "播放")
                    }
                    IconButton(onClick = onDelete) {
                        Icon(
                            Icons.Filled.Delete,
                            contentDescription = "删除",
                            tint = MaterialTheme.colorScheme.error
                        )
                    }
                }
            }
        }
    }
}

/** 来源 chip 的中文(后端 source_label: mission/polish/manual)。 */
private fun sourceLabelCn(sourceLabel: String): String = when (sourceLabel) {
    "mission" -> "实战"
    "polish" -> "润色"
    "manual" -> "手动"
    else -> sourceLabel
}

@Composable
private fun PolishDialog(isPolishing: Boolean, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var text by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text("润色一句") },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.s2)) {
                Text(
                    text = "输入一句英文, AI 给出更好的说法, 并自动收进表达库。",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                OutlinedTextField(
                    value = text,
                    onValueChange = { text = it },
                    modifier = Modifier.fillMaxWidth(),
                    minLines = 2,
                    placeholder = { Text("Type an English sentence…") }
                )
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(text) },
                enabled = text.isNotBlank() && !isPolishing
            ) {
                Text(if (isPolishing) "润色中…" else "润色并收藏")
            }
        },
        dismissButton = {
            TextButton(onClick = onDismiss) {
                Text("取消")
            }
        }
    )
}
