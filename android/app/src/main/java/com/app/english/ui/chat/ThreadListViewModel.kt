package com.app.english.ui.chat

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.ChatRepository
import com.app.english.data.repository.EnglishRepository
import com.app.english.data.repository.GenerateRepository
import com.app.english.domain.model.DialogueScene
import com.app.english.domain.model.ThreadSummary
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 会话列表的一行: 场景素材 join 已有会话 (没聊过的场景也要出现在列表里)。 */
data class ThreadRow(
    val sceneKey: String,
    val title: String,
    val description: String,
    /** 场景素材; 会话指向一个已消失的场景时为 null (只留标题占位, 但**不许**丢掉这一行)。 */
    val scene: DialogueScene?,
    /** 已有会话的线程 id; 没聊过是空串 —— 删除只对这个 id 有效 (sceneKey 不是线程 id)。 */
    val threadId: String = "",
    val preview: String = "",
    val unread: Int = 0,
    val lastAt: String = ""
) {
    /** 这一行背后有没有真实会话 (决定排序: 聊过的在前)。 */
    val threaded: Boolean get() = preview.isNotBlank() || lastAt.isNotBlank() || unread > 0

    companion object {
        fun of(
            sceneKey: String,
            title: String,
            description: String,
            scene: DialogueScene?,
            summary: ThreadSummary?
        ): ThreadRow = ThreadRow(
            sceneKey = sceneKey,
            title = title,
            description = description,
            scene = scene,
            preview = summary?.preview.orEmpty(),
            threadId = summary?.id.orEmpty(),
            unread = summary?.unread ?: 0,
            lastAt = summary?.lastAt.orEmpty()
        )
    }
}

data class ThreadListState(
    val rows: List<ThreadRow> = emptyList(),
    val loading: Boolean = true,
    val error: String? = null,
    /** 自定义场景生成中 (202 -> 轮询); null = 没有在建的。 */
    val generating: String? = null,
    val customSceneError: String? = null
)

/**
 * 微信式会话列表 (= 场景列表)。
 *
 * 列表 = 场景目录 ∪ 已有会话: 目录保证「还有 12 个地方可聊」一直看得见, 会话保证
 * 聊过的场景带着预览与未读红点排在前面。两边都拉不到时才显示错误 —— 只有目录拉到了
 * 就照常可聊 (会话接口挂了最多是预览没了, 不该把整个 App 变成错误页)。
 */
@HiltViewModel
class ThreadListViewModel @Inject constructor(
    private val chatRepository: ChatRepository,
    private val englishRepository: EnglishRepository,
    private val generateRepository: GenerateRepository
) : ViewModel() {

    private val _state = MutableStateFlow(ThreadListState())
    val state: StateFlow<ThreadListState> = _state.asStateFlow()

    init {
        refresh()
    }

    fun refresh() {
        viewModelScope.launch {
            _state.update { it.copy(loading = true, error = null) }
            val scenes = runCatching { englishRepository.listDialogueScenes() }.getOrNull()
            val threads = runCatching { chatRepository.listThreads() }.getOrNull()
            if (scenes == null && threads == null) {
                _state.update { it.copy(loading = false, error = "拿不到场景列表, 检查服务器地址后重试") }
                return@launch
            }
            _state.update {
                it.copy(rows = buildRows(scenes.orEmpty(), threads.orEmpty()), loading = false)
            }
        }
    }

    fun startCustomScene(brief: String) {
        val text = brief.trim()
        if (text.length !in MIN_BRIEF..MAX_BRIEF) {
            _state.update {
                it.copy(customSceneError = "多说几个字 (${MIN_BRIEF}-$MAX_BRIEF), 比如「在咖啡店点一杯喝的」")
            }
            return
        }
        viewModelScope.launch {
            _state.update { it.copy(generating = "正在生成场景…", customSceneError = null) }
            try {
                val jobId = generateRepository.startCustomScene(text)
                pollUntilReady(jobId)
            } catch (e: Exception) {
                _state.update {
                    it.copy(generating = null, customSceneError = "场景生成失败: ${e.message}")
                }
            }
        }
    }

    private suspend fun pollUntilReady(jobId: String) {
        var waitMillis = FAST_POLL_MILLIS
        repeat(MAX_POLLS) {
            delay(waitMillis)
            val job = runCatching { generateRepository.pollJob(jobId) }.getOrNull()
            when {
                job == null -> Unit
                job.isReady -> {
                    _state.update { it.copy(generating = null) }
                    refresh()
                    return
                }
                job.isFailed -> {
                    _state.update {
                        it.copy(
                            generating = null,
                            customSceneError =
                            job.error ?: "场景生成失败"
                        )
                    }
                    return
                }
                else -> _state.update { it.copy(generating = job.stageText.ifBlank { "正在生成场景…" }) }
            }
            waitMillis = (waitMillis * 2).coerceAtMost(MAX_POLL_MILLIS)
        }
        _state.update { it.copy(generating = null, customSceneError = "生成超时, 稍后在列表里看看") }
    }

    /** 长按删除: 只删会话, 场景本身留在目录里 (下次还能聊)。 */
    fun deleteThread(threadId: String) {
        viewModelScope.launch {
            runCatching { chatRepository.deleteThread(threadId) }
            refresh()
        }
    }

    companion object {
        const val MIN_BRIEF = 4
        const val MAX_BRIEF = 200
        const val FAST_POLL_MILLIS = 2_000L
        const val MAX_POLL_MILLIS = 8_000L
        const val MAX_POLLS = 30

        /**
         * 目录与会话的合并: 聊过的排前面 (按最近活跃倒序), 没聊过的按目录顺序跟在后面 ——
         * 微信就是这个秩序。
         *
         * 会话指向一个**已从目录消失**的场景 (自定义场景被删掉或还没就绪) 时不静默丢弃:
         * 用户会看见"我聊过的东西不见了", 那比多一行没有标题的会话更糟。
         */
        fun buildRows(scenes: List<DialogueScene>, threads: List<ThreadSummary>): List<ThreadRow> {
            val byScene = threads.associateBy { it.sceneId }
            val catalogRows = scenes.map { scene ->
                ThreadRow.of(scene.id, scene.title, scene.description, scene, byScene[scene.id])
            }
            val known = scenes.mapTo(HashSet()) { it.id }
            val orphans = threads.filterNot { it.sceneId in known }.map {
                ThreadRow.of(it.sceneId, it.sceneId, "", null, it)
            }
            val engaged = (
                orphans + catalogRows.filter {
                    it.threaded
                }
                ).sortedByDescending { it.lastAt }
            return engaged + catalogRows.filterNot { it.threaded }
        }
    }
}
