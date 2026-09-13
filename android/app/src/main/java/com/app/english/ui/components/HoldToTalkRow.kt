package com.app.english.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.width
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Mic
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.app.english.audio.RecordingTakeClock
import com.app.english.ui.theme.Spacings
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.StateFlow

/** 两种录音行里声量脉冲条的共用高度。 */
private val PULSE_HEIGHT: Dp = 36.dp

/**
 * 长按录音面(短句: 打基础 / 跟读 / 角色对话 / 弱词本 / 测评朗读)的统一布局 ——
 * 实时声量脉冲 + 一个 [HoldToTalkButton] + 话术列。
 *
 * 为什么要这一层: 这几个面的"脉冲 + 话筒 + 话术"本来是各自手抄的同一份 Column, 而
 * "手抄"恰恰是问题 1 的成因 —— `2fd067d` 只把两处换成 HoldToTalkButton, 另外三处照旧
 * 是点按 Button, 用户看到的就是一半屏幕说长按、一半屏幕点按。收成一个组件后手势只有
 * 一份实现可改。实战页(InputBar)不套这个: 它的话筒是嵌在输入框那一行的行内小按钮,
 * 只借用 [RecordingPulseMeter]。
 *
 * 入参打进一个类而不是平铺形参: `app/config/detekt.yml` 的
 * `LongParameterList.functionThreshold = 8`, 而这一行的输入(电平流 + 两个状态位 +
 * 权限 + 三个回调 + 话术)本来就超了。
 *
 * 话术是**入参**、并且画在兄弟 [Text] 上, 这是硬约束而不是风格: 录音/评分态绝不能进入
 * 节点身份 —— 在 `isRecording`/`isSubmitting` 的分支间换 Button 调用点会销毁在途
 * `interactionSource`, 把触发那次翻转的按压静静吃掉(旧实现真发生过, 见
 * [HoldToTalkButton])。P4 把"评分中"升级成整张评分卡时, 换的也只是话术这个兄弟槽位。
 */
@Composable
fun HoldToTalkRow(row: HoldToTalkRowUi, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        RecordingPulseMeter(
            level = row.level,
            presentation = PulseMeterGeometry.presentation(row.isRecording, row.isBusy),
            height = PULSE_HEIGHT
        )
        Row(verticalAlignment = Alignment.CenterVertically) {
            HoldToTalkButton(
                isRecording = row.isRecording,
                enabled = !row.isBusy,
                micGranted = row.micGranted,
                onRequestPermission = row.onRequestPermission,
                onStart = row.onStart,
                onStop = row.onStop
            )
            Spacer(Modifier.width(Spacings.s2))
            Text(
                text = row.labels.label(row.isRecording, row.isBusy),
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/** [HoldToTalkRow] 的入参。 */
class HoldToTalkRowUi(
    val level: StateFlow<Float>,
    val isRecording: Boolean,
    /** 在途(评分中 / 正在准备标准音): 排空按压, 但**不**换手势节点。 */
    val isBusy: Boolean,
    val micGranted: Boolean,
    val onRequestPermission: () -> Unit,
    val onStart: () -> Unit,
    val onStop: () -> Unit,
    val labels: HoldToTalkCopy = HoldToTalkCopy()
)

/** 长按面三态话术。默认值是微信式"按住说话"; 各面按下游动作微调。 */
data class HoldToTalkCopy(
    val idle: String = "按住说话 · 松开发送",
    val holding: String = "松开完成录音",
    val busy: String = "评分中…"
) {
    fun label(isRecording: Boolean, isBusy: Boolean): String = when {
        isBusy -> busy
        isRecording -> holding
        else -> idle
    }
}

/**
 * 点按录音面(长录音: 影子跟读整段连续、自由对话一轮很长 —— 都超出"能按住不松手"的
 * 长度, 计划 D4 明确**保留**点按)的统一布局。
 *
 * 点按换来的是两样诚实性補丁:
 *  1. 文案说"点一下", 不再谎称"长按/按住";
 *  2. 一个真的在走的已用时([TakeElapsedText]) + (有上限时)自动发送提示 —— 用户报的
 *     "录音条坐在那儿不动"里, 另一半其实是"按下之后界面没有任何还在录的证据"。
 *
 * 节点稳定性与长按面同源: 全程只有**一个** [Button] 节点, 状态只改它的文案/配色/图标。
 */
@Composable
fun TapToTalkRow(row: TapToTalkRowUi, modifier: Modifier = Modifier) {
    Column(
        modifier = modifier,
        verticalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        RecordingPulseMeter(
            level = row.level,
            presentation = PulseMeterGeometry.presentation(row.isRecording, row.isBusy),
            height = PULSE_HEIGHT
        )
        Button(
            onClick = { if (row.isRecording) row.onStop() else row.onIdleTap() },
            enabled = !row.isBusy,
            colors = ButtonDefaults.buttonColors(
                containerColor = if (row.isRecording) {
                    MaterialTheme.colorScheme.error
                } else {
                    MaterialTheme.colorScheme.primary
                }
            ),
            modifier = Modifier.fillMaxWidth()
        ) {
            Icon(
                imageVector = if (row.isRecording) Icons.Filled.Stop else row.display.idleIcon,
                contentDescription = null
            )
            Spacer(Modifier.width(8.dp))
            Text(row.display.label(row.isRecording, row.isBusy))
        }
        val live = row.display.startedAtMs.takeIf { row.isRecording }
        TakeElapsedText(startedAtMs = live, capMs = row.display.capMs)
    }
}

/**
 * [TapToTalkRow] 的入参。计时入参与话术合成一个 [display]: detekt 的
 * `LongParameterList` 门槛是函数 8 / 构造器 9, 这一行的输入本来就已经贴边。
 */
class TapToTalkRowUi(
    val level: StateFlow<Float>,
    val isRecording: Boolean,
    /** 在途(评分中 / 准备标准音): 点按被禁用, 但按钮节点保持不变。 */
    val isBusy: Boolean,
    val micGranted: Boolean,
    val onRequestPermission: () -> Unit,
    val onStart: () -> Unit,
    val onStop: () -> Unit,
    val display: TapToTalkDisplay = TapToTalkDisplay()
) {
    /** 无权限时点一下只申请权限, 绝不进录音态(否则界面在演一场没开麦的录音)。 */
    fun onIdleTap() = if (micGranted) onStart() else onRequestPermission()
}

/**
 * 点按面要展示的东西: 三态话术 + 空闲图标(影子跟读进场是"开始一整段", 不是"说一句话")
 * + 计时入参。
 *
 * [startedAtMs] 是本次开录的墙钟毫秒, [capMs] 是**真的**传给 `AudioRecorder.start`
 * 的上限(null = 这条不会自动发送)。各 VM 只在开录时赋 [startedAtMs]、停录时不重置
 * (重置得散在五条退出路径上, 漏一条就是一个静静往上累假的计时器), 所以由
 * [TapToTalkRow] 用 isRecording 一次性门控。
 */
data class TapToTalkDisplay(
    val idle: String = "点一下开始回答",
    val holding: String = "点一下结束并发送",
    val busy: String = "评分中…",
    val idleIcon: ImageVector = Icons.Filled.Mic,
    val startedAtMs: Long? = null,
    val capMs: Long? = null
) {
    fun label(isRecording: Boolean, isBusy: Boolean): String = when {
        isBusy -> busy
        isRecording -> holding
        else -> idle
    }
}

/**
 * 录音进行中的已用时; 空闲时退化成"这条会不会自动发送"的提示。
 *
 * 算术与文案全在 [RecordingTakeClock](纯 Kotlin + 注入 now, 有单测钉住边界), 这里只
 * 负责按 [TICK_INTERVAL_MS] 掀一次重组 —— 组合项里不留任何时间减法, 免得各处又长出一
 * 份 `System.currentTimeMillis() - start` 的方言。
 *
 * [capMs] 为 null(影子跟读没有上限)时 [RecordingTakeClock.capHint] 返回 null: 空闲态
 * 什么都不画, 也永远不会出现"即将自动发送"那种吓唬。
 */
@Composable
fun TakeElapsedText(startedAtMs: Long?, capMs: Long?, modifier: Modifier = Modifier) {
    var nowMs by remember { mutableLongStateOf(System.currentTimeMillis()) }
    LaunchedEffect(startedAtMs) {
        if (startedAtMs != null) {
            while (true) {
                nowMs = System.currentTimeMillis()
                delay(TICK_INTERVAL_MS)
            }
        }
    }
    val elapsedMs = startedAtMs?.let { RecordingTakeClock.elapsedMs(it, nowMs) } ?: 0L
    val text = if (startedAtMs != null) {
        RecordingTakeClock.takeElapsedLabel(startedAtMs, nowMs, capMs)
    } else {
        RecordingTakeClock.capHint(capMs)
    }
    if (text == null) return
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        color = if (RecordingTakeClock.isNearCap(elapsedMs, capMs)) {
            MaterialTheme.colorScheme.error
        } else {
            MaterialTheme.colorScheme.onSurfaceVariant
        },
        modifier = modifier
    )
}

/** 计时刷新节奏: 250 ms 足够让 0:07→0:08 看起来准时, 又不必按帧整页重组。 */
private const val TICK_INTERVAL_MS = 250L
