package com.app.english.ui.player

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Card
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp

/**
 * Shared "how do I get the user's voice?" widgets used by every practice mode.
 *
 *  - [PermissionHint] surfaces when RECORD_AUDIO is missing.
 *  - [ReferenceButton] plays the standard-pronunciation TTS.
 *  - [RecordButton] is the primary action (start / stop / re-record).
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
 * Single button that toggles between "start recording", "stop & submit",
 * and "re-record after a low score" depending on the current state.
 */
@Composable
fun RecordButton(
    isRecording: Boolean,
    isSubmitting: Boolean,
    hasScore: Boolean,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStartRecording: () -> Unit,
    onStopAndSubmit: () -> Unit,
    modifier: Modifier = Modifier
) {
    when {
        isSubmitting -> Button(
            onClick = {},
            modifier = modifier.fillMaxWidth(),
            enabled = false
        ) { Text("评分中...") }
        isRecording -> Button(
            onClick = onStopAndSubmit,
            modifier = modifier.fillMaxWidth(),
            colors = ButtonDefaults.buttonColors(containerColor = MaterialTheme.colorScheme.error)
        ) {
            Icon(Icons.Filled.Stop, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text("停止录音并评分")
        }
        else -> Button(
            onClick = { if (micGranted) onStartRecording() else onRequestPermission() },
            modifier = modifier.fillMaxWidth()
        ) {
            Icon(Icons.Filled.Mic, contentDescription = null)
            Spacer(Modifier.width(8.dp))
            Text(if (hasScore) "重录" else "开始录音")
        }
    }
}

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
