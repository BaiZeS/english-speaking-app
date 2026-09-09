package com.app.english.ui.components

import androidx.compose.foundation.LocalIndication
import androidx.compose.foundation.background
import androidx.compose.foundation.gestures.awaitEachGesture
import androidx.compose.foundation.gestures.awaitFirstDown
import androidx.compose.foundation.indication
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.interaction.PressInteraction
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.hapticfeedback.HapticFeedbackType
import androidx.compose.ui.input.pointer.AwaitPointerEventScope
import androidx.compose.ui.input.pointer.PointerEventPass
import androidx.compose.ui.input.pointer.PointerId
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.platform.LocalHapticFeedback
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.launch

/**
 * WeChat-style "hold to talk" mic button: recording starts the instant the
 * finger lands (with a h tick and an immediate red/Stop restyle) and stops -
 * sending the take - on release. This replaces the old fake where the copy
 * promised 按住说话 but the widget was a plain onClick toggle that only fired
 * on ACTION_UP, so holding appeared dead and releasing started a take the
 * user thought they'd just finished.
 *
 * Gestures are grabbed at the deepest node and every change is consumed, so
 * the surrounding verticalScroll can never steal the press on finger drift
 * (the classic "press long, drag a little, tap silently vanishes"), and the
 * primary pointer is tracked by id so a stray second finger can't end or
 * extend the take. Release (UP) and system cancellation both stop+send —
 * dropping a take is worse than sending a short one, and the AudioRecord is
 * always closed.
 *
 * When [enabled] is false (mid-submit) presses are drained without effect;
 * when mic permission is missing a press only raises the permission request,
 * never recording state, so the button never shows a fake live take.
 *
 * All callbacks flow through rememberUpdatedState and pointerInput(Unit)
 * never restarts, so recompositions during a hold can't cancel or replay the
 * in-flight gesture.
 */
@Composable
fun HoldToTalkButton(
    isRecording: Boolean,
    enabled: Boolean,
    micGranted: Boolean,
    onRequestPermission: () -> Unit,
    onStart: () -> Unit,
    onStop: () -> Unit,
    modifier: Modifier = Modifier,
    buttonSize: Dp = 72.dp,
    iconSize: Dp = 32.dp
) {
    var pressed by remember { mutableStateOf(false) }
    val currentEnabled by rememberUpdatedState(enabled)
    val currentGranted by rememberUpdatedState(micGranted)
    val currentOnStart by rememberUpdatedState(onStart)
    val currentOnStop by rememberUpdatedState(onStop)
    val currentOnRequestPermission by rememberUpdatedState(onRequestPermission)
    val haptics = LocalHapticFeedback.current
    val interactionSource = remember { MutableInteractionSource() }
    // awaitEachGesture runs in a *restricted* coroutine that can only call member
    // suspend functions of PointerInputScope; MutableInteractionSource.emit is a
    // plain suspend fn, so hop onto this (unrestricted) composable scope to push
    // the press/release interactions that drive the ripple + color indication.
    val scope = rememberCoroutineScope()
    val showing = isRecording || pressed
    val disabledAlpha = if (enabled) 1f else 0.38f
    val containerColor = if (showing) {
        MaterialTheme.colorScheme.error
    } else {
        MaterialTheme.colorScheme.primary
    }.copy(alpha = disabledAlpha)

    Box(
        modifier = modifier
            .size(buttonSize)
            .clip(CircleShape)
            .background(containerColor)
            .indication(interactionSource, LocalIndication.current)
            .pointerInput(Unit) {
                awaitEachGesture {
                    val down = awaitFirstDown(requireUnconsumed = false)
                    down.consume()
                    when {
                        !currentEnabled -> drainUntilUp(down.id)
                        !currentGranted -> {
                            currentOnRequestPermission()
                            drainUntilUp(down.id)
                        }
                        else -> {
                            pressed = true
                            haptics.performHapticFeedback(HapticFeedbackType.LongPress)
                            val press = PressInteraction.Press(down.position)
                            scope.launch { interactionSource.emit(press) }
                            currentOnStart()
                            drainUntilUp(down.id)
                            pressed = false
                            scope.launch { interactionSource.emit(PressInteraction.Release(press)) }
                            currentOnStop()
                        }
                    }
                }
            },
        contentAlignment = Alignment.Center
    ) {
        Icon(
            imageVector = if (showing) Icons.Filled.Stop else Icons.Filled.Mic,
            contentDescription = if (showing) "松开发送" else "按住说话",
            tint = MaterialTheme.colorScheme.onPrimary,
            modifier = Modifier.size(iconSize)
        )
    }
}

/**
 * Holds the gesture until the primary pointer lifts (release) or dies
 * (system cancel); consumes every change while waiting so no scrollable
 * parent can claim the drag. Secondary fingers never end the take — only
 * the tracked pointer leaving does.
 */
private suspend fun AwaitPointerEventScope.drainUntilUp(primaryId: PointerId) {
    var finished = false
    while (!finished) {
        val event = awaitPointerEvent(PointerEventPass.Main)
        for (change in event.changes) {
            if (change.pressed || change.previousPressed) change.consume()
            if (change.id == primaryId && !change.pressed) finished = true
        }
    }
}
