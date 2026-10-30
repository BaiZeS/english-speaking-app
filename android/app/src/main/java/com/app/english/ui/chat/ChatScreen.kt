package com.app.english.ui.chat

import android.Manifest
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ChatBubbleKind
import com.app.english.ui.components.RecordingGuard
import com.app.english.ui.theme.Spacings
import com.google.accompanist.permissions.ExperimentalPermissionsApi
import com.google.accompanist.permissions.isGranted
import com.google.accompanist.permissions.rememberPermissionState

/**
 * 一个场景的微信式群聊。
 *
 * 输入栏**没有语言切换控件** —— 语音一律走后端 `zh_cn` 中英混读听写 (实测吃中英混读),
 * 学员说了中文还是英文由服务端从转写文本事后判, 判出来只决定要不要跑英文逐词发音分。
 */
@OptIn(ExperimentalPermissionsApi::class)
@Composable
fun ChatScreen(sceneKey: String, onBack: () -> Unit, viewModel: ChatViewModel = hiltViewModel()) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    val playingId by viewModel.playingId.collectAsStateWithLifecycle()
    val playbackError by viewModel.playbackError.collectAsStateWithLifecycle()
    val micPermission = rememberPermissionState(Manifest.permission.RECORD_AUDIO)

    LaunchedEffect(sceneKey) {
        viewModel.open(sceneKey, micGranted = micPermission.status.isGranted)
    }
    // 离开这一屏时把在录的那一枪交出去: 宁可晚发也别丢 (RecordingGuard 的既定语义)。
    RecordingGuard(onStop = { viewModel.stopAndSend() })

    Scaffold { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(WeChatBackground)
        ) {
            MessageList(
                state = state,
                playingId = playingId,
                onTap = { viewModel.onBubbleTap(it) },
                onLongPress = { viewModel.onBubbleLongPress(it) },
                modifier = Modifier.weight(1f)
            )
            ErrorLine(playbackError?.let { "播放失败: $it" })
            ErrorLine(state.translateError)
            ErrorLine(state.turnError)
            ChatInputRow(
                state = state,
                viewModel = viewModel,
                micGranted = micPermission.status.isGranted,
                onRequestMic = { micPermission.launchPermissionRequest() },
                onBack = onBack
            )
        }
    }
}

@Composable
private fun MessageList(
    state: ChatUiState,
    playingId: String?,
    onTap: (com.app.english.domain.model.ChatMessage) -> Unit,
    onLongPress: (com.app.english.domain.model.ChatMessage) -> Unit,
    modifier: Modifier = Modifier
) {
    val rolesById = state.roles.associateBy { it.id }
    LazyColumn(
        modifier = modifier.fillMaxWidth(),
        // 反向布局 + 反向列表 = 最新一条贴在底部, 这是聊天界面的基本物理。
        reverseLayout = true,
        contentPadding = PaddingValues(vertical = Spacings.s2)
    ) {
        items(state.messages.asReversed(), key = { bubbleKey(it) }) { message ->
            when (message.kind) {
                ChatBubbleKind.HINT -> HintBubble(
                    message = message,
                    expanded = state.expanded.contains(message.id),
                    onToggle = { onTap(message) },
                    onLongPress = { onLongPress(message) }
                )
                ChatBubbleKind.GRADE -> {
                    val render = gradeRender(message.grade)
                    if (render.visible) GradeBubble(render = render)
                }
                else -> ChatBubble(
                    message = message,
                    role = rolesById[message.roleId] ?: unnamedRole(message),
                    view = BubbleView(
                        showingCn = state.expanded.contains(message.id),
                        playing = playingId == message.id,
                        translated = state.translations[message.id]
                    ),
                    onTap = { onTap(message) },
                    onLongPress = { onLongPress(message) }
                )
            }
        }
    }
}

/**
 * 角色表还没到货 (或这个 role_id 对不上) 时的兜底头像。
 *
 * 只兜**显示**: 昵称退化成 `role_id`, 绝不因此不渲染这颗气泡 —— 台词已经生成好了,
 * 没头像也得让人看见说了什么。
 */
private fun unnamedRole(message: com.app.english.domain.model.ChatMessage) =
    com.app.english.domain.model.SceneRole(
        id = message.roleId,
        name = message.roleId.ifBlank { "教练" }
    )

@Composable
private fun ErrorLine(message: String?) {
    if (message.isNullOrBlank()) return
    Text(
        text = message,
        color = MaterialTheme.colorScheme.error,
        fontSize = 12.sp,
        modifier = Modifier.padding(horizontal = Spacings.s2)
    )
}
