package com.app.english.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.app.english.domain.model.ChatBubbleKind
import com.app.english.domain.model.ChatMessage
import com.app.english.domain.model.SceneRole
import com.app.english.ui.components.BilingualText
import com.app.english.ui.theme.Spacings

/**
 * 微信配色的聊天底色。背景 `#EDEDED`、角色气泡白、我的气泡 `#95EC69`、昵称 `#576B95` ——
 * 这四色就是"像微信"的全部必要条件, 缺一个都会立刻变成"一个仿微信的四不像"。
 */
internal val WeChatBackground = Color(0xFFEDEDED)
internal val WeChatPeerBubble = Color(0xFFFFFFFF)
internal val WeChatMineBubble = Color(0xFF95EC69)
internal val WeChatNickname = Color(0xFF576B95)

// 微信式尺寸: 气泡圆角、头像直径、语音条波形。写死在调用点上会让"为什么是 12"无从查起。
internal const val BUBBLE_RADIUS_DP = 12
internal const val BUBBLE_TAIL_RADIUS_DP = 2
internal const val AVATAR_DIAMETER_DP = 40
internal const val AVATAR_LIST_DIAMETER_DP = 42
internal const val AVATAR_OVERLAP_DP = -10
internal const val UNREAD_DOT_DIAMETER_DP = 8
internal const val VOICE_BAR_WIDTH_DP = 3
internal const val VOICE_BAR_STEP_DP = 5

/** 波形条高的循环周期: 4 根一档起伏, 纯装饰 (没有解码振幅这回事)。 */
internal const val VOICE_BAR_HEIGHT_CYCLE = 4
internal const val UNREAD_RED = 0xFFF56C6C
internal const val HINT_BACKGROUND = 0xFFFFF7E6
internal const val HINT_BORDER = 0xFFF0DFB4

/** 头像色板的确定性来源: 同一个角色名永远同一个颜色 (随机色会让重进会话时头像变脸)。 */
private val AVATAR_COLORS = listOf(
    Color(0xFF5B8FF9),
    Color(0xFF61C0A8),
    Color(0xFFFAAD64),
    Color(0xFFE86A6A),
    Color(0xFF8C7DE8),
    Color(0xFF4BC0C8)
)

internal fun avatarColorFor(seed: String): Color = AVATAR_COLORS[
    (seed.hashCode().let { if (it == Int.MIN_VALUE) 0 else kotlin.math.abs(it) }) %
        AVATAR_COLORS.size
]

/** 首字圆形色块头像 —— 不引入任何图片资源, 也不依赖网络。 */
@Composable
fun RoleAvatar(role: SceneRole, modifier: Modifier = Modifier, size: Int = 40) {
    val label = role.name.trim().ifBlank { role.id }.take(1)
    Box(
        modifier = modifier
            .size(size.dp)
            .background(avatarColorFor(role.id.ifBlank { role.name }), CircleShape),
        contentAlignment = Alignment.Center
    ) {
        Text(
            text = label.ifBlank { "?" },
            color = Color.White,
            fontWeight = FontWeight.Bold,
            fontSize = (size / 2.4f).sp
        )
    }
}

/**
 * 微信语音条: 时长 + 几根波形条 + 未播红点。
 *
 * 波形是**装饰**, 不是解码出来的振幅 —— 我们没有也不该有客户端解码音频求包络这条链路;
 * 条数按时长给一个微信式密度 ([voiceBarBars])。播放中逐段点亮由 [progress] 驱动。
 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun VoiceBar(
    audioMs: Long,
    mine: Boolean,
    modifier: Modifier = Modifier,
    playing: Boolean = false,
    progress: Float = 0f,
    unseen: Boolean = false
) {
    val bars = voiceBarBars(audioMs)
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacings.tiny)
    ) {
        if (!mine) {
            // 微信把时长放在另一侧, 让"我发的"和"对方发的"语音条镜像对称。
            Text(voiceBarLabel(audioMs), fontSize = 13.sp)
            Spacer(Modifier.width(Spacings.s1))
        }
        repeat(bars) { index ->
            val lit = playing && index <= (progress * bars).toInt()
            Box(
                modifier = Modifier
                    .width(VOICE_BAR_WIDTH_DP.dp)
                    .height((VOICE_BAR_STEP_DP * (index % VOICE_BAR_HEIGHT_CYCLE + 1)).dp)
                    .background(
                        if (lit) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant.copy(
                                alpha = 0.45f
                            )
                        },
                        RoundedCornerShape(2.dp)
                    )
            )
        }
        if (mine) {
            Spacer(Modifier.width(Spacings.s1))
            Text(voiceBarLabel(audioMs), fontSize = 13.sp)
            if (unseen) {
                Spacer(Modifier.width(Spacings.s1))
                Box(
                    modifier = Modifier
                        .size(8.dp)
                        .background(Color(UNREAD_RED), CircleShape)
                )
            }
        }
    }
}

/** 一颗气泡在当前这一帧的展示态 (都是设备上的临时状态, 不进后端 DTO 契约)。 */
data class BubbleView(
    val showingCn: Boolean = false,
    val playing: Boolean = false,
    val translated: String? = null
)

/** 一条气泡: 语音条形态或文本形态, 长按翻译、点击展开都挂在整颗气泡上。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun ChatBubble(
    message: ChatMessage,
    role: SceneRole,
    view: BubbleView,
    onTap: () -> Unit,
    onLongPress: () -> Unit,
    modifier: Modifier = Modifier
) {
    val showingCn = view.showingCn
    val mine = message.kind == ChatBubbleKind.USER
    val shape = RoundedCornerShape(
        topStart = if (mine) BUBBLE_RADIUS_DP.dp else BUBBLE_TAIL_RADIUS_DP.dp,
        topEnd = if (mine) BUBBLE_TAIL_RADIUS_DP.dp else BUBBLE_RADIUS_DP.dp,
        bottomStart = BUBBLE_RADIUS_DP.dp,
        bottomEnd = BUBBLE_RADIUS_DP.dp
    )
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacings.s2, vertical = Spacings.s1),
        horizontalAlignment = if (mine) Alignment.End else Alignment.Start
    ) {
        if (!mine) {
            Text(role.name, color = WeChatNickname, fontSize = 12.sp)
            Spacer(Modifier.height(Spacings.tiny))
        }
        // 点击(播放+展开)与长按(翻译)必须在同一个手势节点上: 套两层容器会让长按被子节点
        // 的点击吃掉, 表现就是"长按没反应"。
        Column(
            modifier = Modifier
                .combinedClickable(onClick = onTap, onLongClick = onLongPress)
                .clip(shape)
                .background(if (mine) WeChatMineBubble else WeChatPeerBubble, shape)
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            if (message.isVoiceBubble) {
                VoiceBar(
                    audioMs = message.audioMs,
                    mine = mine,
                    playing = view.playing,
                    unseen = message.audioUrl != null && !showingCn
                )
            }
            if (showingCn || !message.isVoiceBubble) {
                val body = message.text.ifBlank { message.recognizedText }
                // 收着中文时传 null 而不是空串: BilingualText 的"次级为空 ⇒ 整行不渲染"
                // 就是这里要的语义, 别自己再造一套开关。
                BilingualText(primary = body, secondary = message.textCn.takeIf { showingCn })
            }
            view.translated?.let {
                Text(
                    text = "译: $it",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
        }
    }
}

/** 建议回答: 默认折叠。这是"用户可以提前获取建议的回答"的实现 —— 数据每轮都随台词返回。 */
@OptIn(ExperimentalFoundationApi::class)
@Composable
fun HintBubble(
    expanded: Boolean,
    onToggle: () -> Unit,
    onLongPress: () -> Unit,
    message: ChatMessage,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacings.s2, vertical = Spacings.tiny)
            .combinedClickable(onClick = onToggle, onLongClick = onLongPress)
            .background(Color(HINT_BACKGROUND), RoundedCornerShape(10.dp))
            .border(1.dp, Color(HINT_BORDER), RoundedCornerShape(10.dp))
            .padding(Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
    ) {
        Text(
            text = if (expanded) "💡 建议回答" else "💡 建议回答 · 看提示",
            fontWeight = FontWeight.Bold,
            fontSize = 13.sp,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        if (expanded) {
            BilingualText(primary = message.text, secondary = message.textCn)
        }
    }
}

/**
 * 评分卡。
 *
 * [GradeRender.visible] 为 false 时**整颗不渲染** —— 包含 `failed`: 点评没有, 但这一轮
 * 存在, 其它气泡一颗都不能少。缺一个轴就不画那一行 (尤其发音: 说中文时没测, 画 0 分
 * 等于说"测了且很差")。
 */
@Composable
fun GradeBubble(render: GradeRender, modifier: Modifier = Modifier) {
    if (!render.visible) return
    Column(
        modifier = modifier
            .fillMaxWidth()
            .padding(horizontal = Spacings.s2, vertical = Spacings.tiny)
            .background(Color.White, RoundedCornerShape(10.dp))
            .padding(Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
    ) {
        if (render.pending) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                CircularProgressIndicator(modifier = Modifier.size(12.dp), strokeWidth = 2.dp)
                Spacer(Modifier.width(Spacings.s1))
                Text("评分生成中…", fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            return@Column
        }
        Text("📊 ${render.scoreLabel}", fontWeight = FontWeight.Bold, fontSize = 15.sp)
        render.axes.forEach { (label, value) ->
            Text(
                "$label $value",
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
        if (render.comment.isNotBlank()) {
            Text(render.comment, fontSize = 13.sp, maxLines = 3, overflow = TextOverflow.Ellipsis)
        }
    }
}

/** 删除会话的确认框 —— 一点就删在聊天产品里是灾难 (整个场景的聊天记录没了)。 */
@Composable
fun ConfirmDeleteThread(onCancel: () -> Unit, onConfirm: () -> Unit) {
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("删除这个场景的聊天记录?") },
        text = { Text("只删这一条会话, 场景本身还在列表里, 随时可以再聊。") },
        confirmButton = { TextButton(onClick = onConfirm) { Text("删除") } },
        dismissButton = { TextButton(onClick = onCancel) { Text("取消") } }
    )
}
