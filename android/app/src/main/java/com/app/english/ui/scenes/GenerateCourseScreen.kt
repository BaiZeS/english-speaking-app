package com.app.english.ui.scenes

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.ui.theme.Spacings

/** 示例目标 chips(可栗同款引导文案)。 */
private val EXAMPLE_GOALS = listOf(
    "下周主持项目会议, 要同步进度和风险",
    "两个月后去伦敦出差, 要办酒店入住",
    "准备 EMBA 英文面试, 能讲清职业规划"
)

/**
 * 生成课程页(计划 §6.4): 大输入框 + 示例 chips + 三段进度动画(理解目标→设计
 * 任务→生成对话) -> ready 打开详情。
 */
@Composable
fun GenerateCourseScreen(
    onBack: () -> Unit,
    onCourseReady: (sceneId: String) -> Unit,
    modifier: Modifier = Modifier,
    viewModel: GenerateCourseViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    LaunchedEffect(state.phase) {
        if (state.phase == GeneratePhase.READY) {
            state.sceneId?.let(onCourseReady)
        }
    }
    Column(
        modifier = modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(Spacings.s3),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        Row(modifier = Modifier.fillMaxWidth()) {
            TextButton(onClick = onBack) { Text("← 返回") }
        }
        when (state.phase) {
            GeneratePhase.INPUT -> InputPhase(state, viewModel::updateGoal, viewModel::start)
            GeneratePhase.GENERATING -> GeneratingPhase(state)
            GeneratePhase.FAILED -> FailedPhase(state, viewModel::start)
            GeneratePhase.READY -> Box(Modifier.fillMaxSize(), Alignment.Center) {
                Text("课程已就绪, 正在打开…")
            }
        }
    }
}

@Composable
private fun InputPhase(
    state: GenerateCourseUiState,
    onGoalChange: (String) -> Unit,
    onStart: () -> Unit
) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s3)) {
        Text("用一句话说出你的学习目标", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = "AI 会据此生成一整节情景课: 词汇 + 打基础 + 实战任务",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        OutlinedTextField(
            value = state.goalText,
            onValueChange = onGoalChange,
            modifier = Modifier
                .fillMaxWidth()
                .height(140.dp),
            placeholder = { Text("例如: 下周要用英文给客户做一次电话回访…") }
        )
        Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
            Text("没有思路? 试试这些:", style = MaterialTheme.typography.labelMedium)
            EXAMPLE_GOALS.forEach { goal ->
                Card(onClick = { onGoalChange(goal) }) {
                    Text(
                        text = goal,
                        modifier = Modifier
                            .fillMaxWidth()
                            .padding(Spacings.s2),
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
        }
        Button(
            onClick = onStart,
            enabled = state.goalText.trim().length >= 4,
            modifier = Modifier
                .fillMaxWidth()
                .height(52.dp)
        ) { Text("生成我的专属课") }
    }
}

@Composable
private fun GeneratingPhase(state: GenerateCourseUiState) {
    val stages = listOf("理解目标", "设计任务", "生成对话")
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s3)) {
        Text("正在为你定制课程…", style = MaterialTheme.typography.headlineSmall)
        Column(verticalArrangement = Arrangement.spacedBy(Spacings.s2)) {
            stages.forEachIndexed { index, label ->
                val reached = index <= state.stageIndex
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(12.dp)
                            .background(
                                color = if (reached) {
                                    MaterialTheme.colorScheme.primary
                                } else {
                                    MaterialTheme.colorScheme.surfaceVariant
                                },
                                shape = RoundedCornerShape(6.dp)
                            )
                    )
                    Box(Modifier.size(Spacings.s2))
                    Text(
                        text = label,
                        style = MaterialTheme.typography.bodyLarge,
                        color = if (reached) {
                            MaterialTheme.colorScheme.primary
                        } else {
                            MaterialTheme.colorScheme.onSurfaceVariant
                        }
                    )
                }
            }
        }
        // 分钟级诚实进度(T5 实测: 每段 200-240s, 全课 5-10 分钟), 不假装 30 秒能出课。
        Text(
            text = "已等 ${state.elapsedSeconds / 60} 分 ${state.elapsedSeconds % 60} 秒 · " +
                "通常需要 5-10 分钟, 完成后自动打开",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        if (state.stageText.isNotBlank()) {
            Card(modifier = Modifier.animateContentSize()) {
                Text(
                    text = state.stageText,
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(Spacings.s2),
                    style = MaterialTheme.typography.bodyMedium
                )
            }
        }
    }
}

@Composable
private fun FailedPhase(state: GenerateCourseUiState, onRetry: () -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s2)) {
        Text("生成失败了", style = MaterialTheme.typography.headlineSmall)
        Text(
            text = state.error ?: "未知错误",
            style = MaterialTheme.typography.bodyMedium,
            color = MaterialTheme.colorScheme.error
        )
        Button(onClick = onRetry, modifier = Modifier.fillMaxWidth()) { Text("再试一次") }
    }
}
