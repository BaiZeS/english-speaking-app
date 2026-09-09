package com.app.english.ui.components

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberUpdatedState
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.compose.LocalLifecycleOwner

/**
 * Calls [onStop] when the host screen's lifecycle reaches ON_STOP while a
 * recording is still live (home button, navigation away, backgrounding).
 * Without this, `collectAsStateWithLifecycle` stops feeding the UI but the
 * AudioRecorder keeps holding the mic, so the next take's start fails and
 * the mic indicator stays stuck on — one of the "unstable" symptoms.
 *
 * [onStop] should route to the ViewModel's stop-and-send (not a discard): the
 * user's spoken take is better delivered late than lost, and every screen
 * already owns such a path. The ViewModel receives the callback as a stable
 * lambda via rememberUpdatedState, so a mid-recording recomposition can't
 * drop a pending stop.
 */
@Composable
fun RecordingGuard(onStop: () -> Unit) {
    val currentOnStop by rememberUpdatedState(onStop)
    val lifecycleOwner = LocalLifecycleOwner.current
    DisposableEffect(lifecycleOwner) {
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP) currentOnStop()
        }
        lifecycleOwner.lifecycle.addObserver(observer)
        onDispose {
            lifecycleOwner.lifecycle.removeObserver(observer)
        }
    }
}
