package com.app.english.ui.chat

import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material.icons.filled.Keyboard
import androidx.compose.material.icons.filled.Send
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.unit.sp
import com.app.english.ui.components.HoldToTalkCopy
import com.app.english.ui.components.HoldToTalkRow
import com.app.english.ui.components.HoldToTalkRowUi
import com.app.english.ui.theme.Spacings

/**
 * 底部输入栏: 左返回、中间「按住说话」或文字框、右切换。
 *
 * 单独成函数不只是长度: 这一行同时管着两种互斥的输入态, 混在 `ChatScreen` 里会把
 * "录音态与提交态必须共用一个手势节点"这条约束 (见 `HoldToTalkRow` 的注释) 埋掉 ——
 * 换节点会销毁在途的 interactionSource, 把触发翻转的那次按压静静吃掉。
 */
@Composable
fun ChatInputRow(
    state: ChatUiState,
    viewModel: ChatViewModel,
    micGranted: Boolean,
    onRequestMic: () -> Unit,
    onBack: () -> Unit
) {
    var textMode by remember { mutableStateOf(false) }
    var draft by remember { mutableStateOf("") }

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .padding(Spacings.s1),
        verticalAlignment = Alignment.CenterVertically
    ) {
        IconButton(onClick = onBack) {
            Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
        }
        if (textMode) {
            OutlinedTextField(
                value = draft,
                onValueChange = { draft = it },
                modifier = Modifier.weight(1f),
                placeholder = { Text("用中文或英文说自己那句", fontSize = 13.sp) },
                maxLines = 3,
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Send),
                keyboardActions = KeyboardActions(
                    onSend = {
                        viewModel.sendText(draft)
                        draft = ""
                    }
                )
            )
            IconButton(
                onClick = {
                    viewModel.sendText(draft)
                    draft = ""
                },
                enabled = draft.isNotBlank() && !state.submitting
            ) {
                Icon(Icons.Default.Send, contentDescription = "发送")
            }
            IconButton(onClick = { textMode = false }) {
                Icon(Icons.Default.Keyboard, contentDescription = "改回按住说话")
            }
        } else {
            HoldToTalkRow(
                row = HoldToTalkRowUi(
                    level = viewModel.recordingLevel,
                    isRecording = state.recording,
                    isBusy = state.submitting,
                    micGranted = micGranted,
                    onRequestPermission = onRequestMic,
                    onStart = { viewModel.startRecording() },
                    onStop = { viewModel.stopAndSend() },
                    // 这一轮没有"评分中"这一步 (判分在请求之外回填), 所以忙态话术说的是
                    // 对方在接话 —— 写"评分中…"会让人以为屏幕卡住了。
                    labels = HoldToTalkCopy(busy = "对方正在接话…")
                ),
                modifier = Modifier.weight(1f)
            )
            IconButton(onClick = { textMode = true }) {
                Icon(Icons.Default.Keyboard, contentDescription = "改用文字输入")
            }
        }
    }
}
