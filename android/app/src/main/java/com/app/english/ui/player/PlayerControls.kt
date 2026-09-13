package com.app.english.ui.player

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import com.app.english.ui.components.HoldToTalkCopy
import com.app.english.ui.components.HoldToTalkRow
import com.app.english.ui.components.HoldToTalkRowUi
import kotlinx.coroutines.flow.StateFlow

/**
 * Shared "how do I get the user's voice?" widgets used by every practice mode.
 *
 *  - [PermissionHint] surfaces when RECORD_AUDIO is missing.
 *  - [ReferenceButton] plays the standard-pronunciation TTS.
 *  - [RecordButton] 是短句面(跟读 / 角色对话)的主动作: 长按说话, 松手送评分。
 *    整段连续的影子跟读不在此列 —— 它按 D4 保留点按手势, 见 PlayerShadowView。
 */

/**
 * Inline card asking the user to grant the microphone permission. Tap the
 * "Grant" button to launch the system dialog.
 */
@Composable
fun PermissionHint(onRequestPermission: () -> Unit, modifier: Modifier = Modifier) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text("需要录音权限才能进行口语练习。")
            Button(onClick = onRequestPermission, modifier = Modifier.padding(top = 8.dp)) {
                Text("授予权限")
            }
        }
    }
}

/**
 * "Play standard pronunciation" call to action, disabled while audio is
 * already streaming.
 */
@Composable
fun ReferenceButton(
    isPlaying: Boolean,
    label: String,
    onClick: () -> Unit,
    modifier: Modifier = Modifier
) {
    OutlinedButton(
        onClick = onClick,
        enabled = !isPlaying,
        modifier = modifier.fillMaxWidth()
    ) {
        Icon(Icons.Filled.PlayArrow, contentDescription = null)
        Spacer(Modifier.width(6.dp))
        Text(if (isPlaying) "播放中..." else label)
    }
}

/**
 * 跟读(READ_ALONG)与角色对话(DIALOGUE)的录音行 —— 长按说话, 松手即送评分。
 *
 * 节点稳定性(这条历史约束的正确表述, 旧注释在这里写反过一次):
 *  - **不安全**: 在 `isRecording`/`isSubmitting` 的 `when` 分支之间更换 Button 调用点。
 *    旧实现就是这么写的, 触发翻转的那次按压会随着在途 `interactionSource` 一起被销毁,
 *    于是一次点按被静静吞掉。本函数(以及 [HoldToTalkRow] / [TapToTalkRow])始终只有
 *    一个手势节点, 状态只改兄弟 [Text] 的文案与配色。
 *  - **安全**: 按 [PlayerMode] 在调用点分派。mode 在 ViewModel 构造时就由 nav arg 定死
 *    (`PlayerViewModel.kt` 的 `private val mode = PlayerMode.fromWire(...)`), 一次按压
 *    期间不可能翻转, 所以"这一面用长按还是点按"这种**结构性**差异尽可以写在调用点。
 *    SHADOW 走 PlayerShadowView 自带的点按行, 不会走到这里。
 *
 * 入参被打成一个类: 本函数原本已有 8 个形参, 正卡在
 * `app/config/detekt.yml:LongParameterList.functionThreshold = 8` 上, 再喂一路流就会被标记。
 */
@Composable
fun RecordButton(controls: RecordControls, modifier: Modifier = Modifier) {
    HoldToTalkRow(
        row = HoldToTalkRowUi(
            level = controls.micLevel,
            isRecording = controls.isRecording,
            isBusy = controls.isSubmitting,
            micGranted = controls.micGranted,
            onRequestPermission = controls.onRequestPermission,
            onStart = controls.onStartRecording,
            onStop = controls.onStopAndSubmit,
            labels = HoldToTalkCopy(
                idle = if (controls.hasScore) "按住重录这一句 · 松开发送" else "按住说话 · 松开发送",
                holding = "松开完成录音",
                busy = "评分中…"
            )
        ),
        modifier = modifier
    )
}

/**
 * [RecordButton] 的入参包(见那里关于 detekt 形参上限的说明)。
 */
data class RecordControls(
    val micLevel: StateFlow<Float>,
    val isRecording: Boolean,
    val isSubmitting: Boolean,
    val hasScore: Boolean,
    val micGranted: Boolean,
    val onRequestPermission: () -> Unit,
    val onStartRecording: () -> Unit,
    val onStopAndSubmit: () -> Unit
)

/** "Next" / "Finish" button gated on whether the current line cleared the threshold. */
@Composable
fun AdvanceButton(
    canAdvance: Boolean,
    isLastLine: Boolean,
    onNext: () -> Unit,
    modifier: Modifier = Modifier
) {
    Button(
        onClick = onNext,
        modifier = modifier.fillMaxWidth(),
        enabled = canAdvance
    ) {
        Text(if (isLastLine) "完成练习" else "下一句")
    }
}
