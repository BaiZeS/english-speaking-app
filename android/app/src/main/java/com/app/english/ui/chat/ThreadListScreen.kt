package com.app.english.ui.chat

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.MoreHoriz
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.SceneRole
import com.app.english.ui.theme.Spacings

/**
 * 微信式会话列表 = 场景列表 (App 首页)。
 *
 * 列表是「场景目录 ∪ 已有会话」: 目录保证"还有地方可聊"一直看得见, 会话保证聊过的
 * 场景带着预览与未读红点排在前面。
 */
@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun ThreadListScreen(
    onOpenScene: (sceneKey: String) -> Unit,
    onOpenSettings: () -> Unit,
    viewModel: ThreadListViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    var showComposer by remember { mutableStateOf(false) }
    var pendingDelete by remember { mutableStateOf<ThreadRow?>(null) }

    Scaffold(
        topBar = {
            TopAppBar(
                title = { Text("情景对话") },
                actions = {
                    IconButton(onClick = { showComposer = true }) {
                        Icon(Icons.Default.Add, contentDescription = "描述一个想聊的场景")
                    }
                    // 设置是**逃生门**: 更新检查失败时必须能从这儿改服务器地址, 否则后端
                    // 不可达时用户被弹窗锁死在所有页面之外 (v2.2.4 的教训)。
                    IconButton(onClick = onOpenSettings) {
                        Icon(Icons.Default.MoreHoriz, contentDescription = "设置")
                    }
                }
            )
        }
    ) { padding ->
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(padding)
                .background(WeChatBackground)
        ) {
            StatusLines(state)
            when {
                state.loading && state.rows.isEmpty() -> Centered { CircularProgressIndicator() }
                state.error != null && state.rows.isEmpty() -> Centered {
                    Column(horizontalAlignment = Alignment.CenterHorizontally) {
                        Text(state.error.orEmpty(), color = MaterialTheme.colorScheme.error)
                        Spacer(Modifier.height(Spacings.s2))
                        TextButton(onClick = { viewModel.refresh() }) { Text("重试") }
                    }
                }
                else -> LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(state.rows, key = { it.sceneKey }) { row ->
                        ThreadRowItem(
                            row = row,
                            onOpen = { onOpenScene(row.sceneKey) },
                            onDeleteRequest = { pendingDelete = row }
                        )
                    }
                }
            }
        }
    }

    if (showComposer) {
        SceneComposerDialog(
            onCancel = { showComposer = false },
            onSubmit = { brief ->
                viewModel.startCustomScene(brief)
                showComposer = false
            }
        )
    }
    pendingDelete?.let { row ->
        ConfirmDeleteThread(
            onCancel = { pendingDelete = null },
            onConfirm = {
                // sceneKey 不是线程 id: 只有真聊过 (拿到过 threadId) 才有可删的东西。
                row.threadId.takeIf { it.isNotBlank() }?.let { viewModel.deleteThread(it) }
                pendingDelete = null
            }
        )
    }
}

@Composable
private fun StatusLines(state: ThreadListState) {
    state.generating?.let { stage ->
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalAlignment = Alignment.CenterVertically
        ) {
            CircularProgressIndicator(modifier = Modifier.size(14.dp), strokeWidth = 2.dp)
            Spacer(Modifier.width(Spacings.s1))
            Text(stage, fontSize = 13.sp, color = MaterialTheme.colorScheme.onSurfaceVariant)
        }
    }
    state.customSceneError?.let { reason ->
        Text(
            text = reason,
            color = MaterialTheme.colorScheme.error,
            fontSize = 12.sp,
            modifier = Modifier.padding(horizontal = Spacings.s2)
        )
    }
}

@Composable
private fun Centered(content: @Composable () -> Unit) {
    Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) { content() }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun ThreadRowItem(row: ThreadRow, onOpen: () -> Unit, onDeleteRequest: () -> Unit) {
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onOpen, onLongClick = onDeleteRequest)
            .background(MaterialTheme.colorScheme.surface)
            .padding(horizontal = Spacings.s2, vertical = Spacings.s2),
        verticalAlignment = Alignment.CenterVertically
    ) {
        AvatarGroup(row.scene?.roles.orEmpty())
        Spacer(Modifier.width(Spacings.s2))
        Column(modifier = Modifier.weight(1f)) {
            Text(row.title, fontWeight = FontWeight.Medium, fontSize = 16.sp)
            Text(
                text = row.preview.ifBlank { row.scene?.description ?: row.description },
                fontSize = 13.sp,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                maxLines = 1,
                overflow = TextOverflow.Ellipsis
            )
        }
        if (row.unread > 0) {
            Box(
                modifier = Modifier
                    .size(UNREAD_DOT_DIAMETER_DP.dp)
                    .background(Color(UNREAD_RED), CircleShape)
            )
        }
    }
}

private const val MAX_STACKED_AVATARS = 3

/** 多角色就叠几个圆 —— 一眼看出这场是单聊还是群聊。 */
@Composable
private fun AvatarGroup(roles: List<SceneRole>) {
    if (roles.isEmpty()) {
        RoleAvatar(SceneRole(id = "", name = "?"))
        return
    }
    Row {
        roles.take(MAX_STACKED_AVATARS).forEachIndexed { index, role ->
            Box(
                modifier = Modifier.offset(
                    x = (index * AVATAR_OVERLAP_DP).dp
                ).zIndex(index.toFloat())
            ) {
                RoleAvatar(role, size = AVATAR_LIST_DIAMETER_DP)
            }
        }
    }
}

@Composable
private fun SceneComposerDialog(onCancel: () -> Unit, onSubmit: (String) -> Unit) {
    var draft by remember { mutableStateOf("") }
    AlertDialog(
        onDismissRequest = onCancel,
        title = { Text("想聊什么场景?") },
        text = {
            Column {
                Text(
                    "一句话就行, 例如「在咖啡店点一杯喝的并和常客闲聊」。",
                    fontSize = 13.sp,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
                Spacer(Modifier.height(Spacings.s2))
                OutlinedTextField(value = draft, onValueChange = { draft = it }, maxLines = 3)
            }
        },
        confirmButton = {
            TextButton(onClick = {
                onSubmit(draft.trim())
            }, enabled = draft.isNotBlank()) { Text("生成") }
        },
        dismissButton = { TextButton(onClick = onCancel) { Text("取消") } }
    )
}
