package com.app.english.ui.settings

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Refresh
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.LlmModel
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun SettingsScreen(modifier: Modifier = Modifier, viewModel: SettingsViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val snackbarHostState = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()

    Scaffold(
        modifier = modifier,
        topBar = { TopAppBar(title = { Text("设置") }) },
        snackbarHost = { SnackbarHost(snackbarHostState) }
    ) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .fillMaxSize()
                .verticalScroll(rememberScrollState())
                .padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(16.dp)
        ) {
            BackendUrlCard(state.baseUrl, viewModel::updateBaseUrl)
            VoiceCard(state.voice, state.availableVoices, viewModel::updateVoice)
            LlmModelCard(
                models = state.llmModels,
                selectedId = state.selectedModelId,
                isLoading = state.isLoadingModels,
                errorMessage = state.llmLoadError,
                onSelect = viewModel::selectModel,
                onRefresh = viewModel::refreshLlmModels
            )
            DeviceIdCard(viewModel.deviceId)

            Button(
                onClick = {
                    viewModel.save()
                    scope.launch { snackbarHostState.showSnackbar("已保存，重启 App 后生效") }
                },
                modifier = Modifier.fillMaxWidth()
            ) {
                Text("保存")
            }
        }
    }
}

@Composable
private fun BackendUrlCard(baseUrl: String, onChange: (String) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("后端地址", style = MaterialTheme.typography.titleMedium)
            OutlinedTextField(
                value = baseUrl,
                onValueChange = onChange,
                modifier = Modifier.fillMaxWidth(),
                label = { Text("Base URL") },
                singleLine = true
            )
            Text(
                text = "默认 http://10.0.2.2:8000/api/v1/（模拟器映射宿主机）",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

@Composable
private fun VoiceCard(current: String, voices: List<String>, onSelect: (String) -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("TTS 音色", style = MaterialTheme.typography.titleMedium)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                voices.forEach { voiceOption ->
                    OutlinedButton(
                        onClick = { onSelect(voiceOption) },
                        enabled = current != voiceOption
                    ) {
                        Text(voiceOption)
                    }
                }
            }
        }
    }
}

@Composable
private fun LlmModelCard(
    models: List<LlmModel>,
    selectedId: String?,
    isLoading: Boolean,
    errorMessage: String?,
    onSelect: (String?) -> Unit,
    onRefresh: () -> Unit
) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("对话模型", style = MaterialTheme.typography.titleMedium)
                Box(modifier = Modifier.weight(1f))
                IconButton(onClick = onRefresh, enabled = !isLoading) {
                    if (isLoading) {
                        CircularProgressIndicator(
                            modifier = Modifier.size(18.dp),
                            strokeWidth = 2.dp
                        )
                    } else {
                        Icon(Icons.Filled.Refresh, contentDescription = "刷新模型列表")
                    }
                }
            }
            Text(
                text = "由后端配置（默认百炼 OpenAI 兼容端点）。选择后下次自由对话生效。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )

            when {
                isLoading && models.isEmpty() -> Text("加载模型列表...")
                models.isEmpty() -> {
                    Text(
                        text = errorMessage ?: "暂无模型（请检查后端是否启动）",
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.error
                    )
                }
                else -> {
                    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                        ModelChoice(
                            label = "使用后端默认",
                            subtitle = "跟随服务器 LLM_DEFAULT_MODEL 配置",
                            selected = selectedId == null,
                            onClick = { onSelect(null) }
                        )
                        models.forEach { model ->
                            ModelChoice(
                                label = model.displayName,
                                subtitle = "${model.id} · ${model.description}".trim(' ', '·'),
                                selected = selectedId == model.id,
                                onClick = { onSelect(model.id) }
                            )
                        }
                    }
                }
            }

            errorMessage?.takeIf { models.isNotEmpty() }?.let {
                Text(
                    text = it,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
        }
    }
}

@Composable
private fun ModelChoice(label: String, subtitle: String, selected: Boolean, onClick: () -> Unit) {
    val container = if (selected) {
        MaterialTheme.colorScheme.primaryContainer
    } else {
        MaterialTheme.colorScheme.surfaceVariant
    }
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(containerColor = container),
        onClick = onClick
    ) {
        Column(Modifier.padding(12.dp)) {
            Text(
                text = label,
                style = MaterialTheme.typography.titleSmall,
                fontWeight = FontWeight.SemiBold
            )
            if (subtitle.isNotBlank()) {
                Text(
                    text = subtitle,
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

@Composable
private fun DeviceIdCard(deviceId: String) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Text("设备 ID", style = MaterialTheme.typography.titleMedium)
            Text(
                text = deviceId,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = "用于标识本机历史记录（device_id）。",
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}
