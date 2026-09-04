package com.app.english.ui.scenes

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.app.english.data.repository.GenerateRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import javax.inject.Inject
import kotlinx.coroutines.delay
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.flow.update
import kotlinx.coroutines.launch

/** 生成页阶段: 输入 -> 轮询 -> 就绪/失败。 */
enum class GeneratePhase { INPUT, GENERATING, READY, FAILED }

data class GenerateCourseUiState(
    val phase: GeneratePhase = GeneratePhase.INPUT,
    val goalText: String = "",
    val progressPercent: Int = 0,
    val stageText: String = "",
    val stageIndex: Int = 0,
    val elapsedSeconds: Long = 0,
    val sceneId: String? = null,
    val error: String? = null
)

/**
 * 生成课程页(计划 §6.4 GenerateCourseScreen): POST /scenes/generate -> 轮询
 * jobs(节奏见 [GeneratePollingPolicy], **分钟级诚实文案**, T5 实测全课 5-10
 * 分钟) -> ready 后打开详情; failed 显示 error 可重试。
 */
@HiltViewModel
class GenerateCourseViewModel @Inject constructor(
    private val generateRepository: GenerateRepository
) : ViewModel() {

    private val _state = MutableStateFlow(GenerateCourseUiState())
    val state: StateFlow<GenerateCourseUiState> = _state.asStateFlow()

    fun updateGoal(text: String) = _state.update { it.copy(goalText = text) }

    fun start() {
        val goal = _state.value.goalText.trim()
        if (goal.length < 4 || _state.value.phase == GeneratePhase.GENERATING) return
        viewModelScope.launch {
            _state.update { it.copy(phase = GeneratePhase.GENERATING, error = null) }
            try {
                val jobId = generateRepository.startGeneration(goal)
                poll(jobId)
            } catch (e: Exception) {
                _state.update {
                    it.copy(phase = GeneratePhase.FAILED, error = e.message ?: "创建生成任务失败")
                }
            }
        }
    }

    private suspend fun poll(jobId: String) {
        val startedAt = System.currentTimeMillis()
        var polls = 0
        while (true) {
            val job = try {
                generateRepository.pollJob(jobId)
            } catch (e: Exception) {
                // 单次轮询失败不放弃(网络抖动), 计入退避节奏。
                _state.update { it.copy(error = null) }
                null
            }
            val elapsed = System.currentTimeMillis() - startedAt
            if (job != null) {
                _state.update {
                    it.copy(
                        progressPercent = (job.progress * 100).toInt(),
                        stageText = job.stageText,
                        stageIndex = GeneratePollingPolicy.stageIndex(job.progress)
                    )
                }
                if (GeneratePollingPolicy.isTerminal(job)) {
                    if (job.isReady && job.sceneId != null) {
                        // 打开详情顺便把整课快照进 course_cache(GenerateRepository)。
                        try {
                            generateRepository.getScene(job.sceneId)
                        } catch (_: Exception) {
                            // 详情拉不动也让流程继续: gallery 合并后仍能再取。
                        }
                        _state.update {
                            it.copy(phase = GeneratePhase.READY, sceneId = job.sceneId)
                        }
                    } else {
                        _state.update {
                            it.copy(
                                phase = GeneratePhase.FAILED,
                                error = job.error ?: "生成失败, 稍后重试"
                            )
                        }
                    }
                    return
                }
            }
            if (GeneratePollingPolicy.isTimedOut(elapsed)) {
                _state.update {
                    it.copy(
                        phase = GeneratePhase.FAILED,
                        error = "生成超时了 (任务仍在后台跑), 稍后从首页画廊查看"
                    )
                }
                return
            }
            _state.update { it.copy(elapsedSeconds = elapsed / 1000) }
            delay(GeneratePollingPolicy.nextDelayMillis(polls))
            polls++
        }
    }
}
