package com.app.english.ui.me

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.History
import androidx.compose.material.icons.filled.Info
import androidx.compose.material.icons.filled.Settings
import androidx.compose.material3.Card
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.PracticeStats
import com.app.english.ui.components.ActionEntryCard
import com.app.english.ui.components.InlineEmptyState
import com.app.english.ui.components.LevelPill
import com.app.english.ui.components.RadarChart
import com.app.english.ui.components.ReviewSuggestionsCard
import com.app.english.ui.components.SectionHeader
import com.app.english.ui.components.StreakCard
import com.app.english.ui.components.SubjectBreakdownCard
import com.app.english.ui.components.TopStatsRow
import com.app.english.ui.components.TrendCard
import com.app.english.ui.theme.Spacings

/**
 * 我的 Tab(计划 §6.3 Tab 4): 能力画像雷达 + 练习概览(原 Dashboard 拆过来的统计
 * 积木) + 历史 / 设置 / 关于入口。
 */
@Composable
fun MeScreen(
    onHistoryClick: () -> Unit,
    onSettingsClick: () -> Unit,
    onAboutClick: () -> Unit,
    onAssessmentClick: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: MeViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(modifier = modifier) { padding ->
        Column(
            modifier = Modifier
                .padding(padding)
                .verticalScroll(rememberScrollState())
                .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s3)
        ) {
            SectionHeader(title = "我的", subtitle = "能力画像与练习足迹")
            AbilityProfileCard(ability = state.ability, onAssessmentClick = onAssessmentClick)
            state.stats?.let { stats -> PracticeSummary(stats = stats) }
            val weakest = state.weakest
            if (weakest.isNotEmpty()) {
                ReviewSuggestionsCard(items = weakest, onClick = onHistoryClick)
            }
            ActionEntryCard(
                title = "练习历史",
                subtitle = "每一次录音与分数都在",
                icon = Icons.Filled.History,
                onClick = onHistoryClick,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant
            )
            ActionEntryCard(
                title = "设置",
                subtitle = "后端地址、主题、发音引擎",
                icon = Icons.Filled.Settings,
                onClick = onSettingsClick,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant
            )
            ActionEntryCard(
                title = "关于",
                subtitle = "版本与使用说明",
                icon = Icons.Filled.Info,
                onClick = onAboutClick,
                containerColor = MaterialTheme.colorScheme.surfaceVariant,
                contentColor = MaterialTheme.colorScheme.onSurfaceVariant
            )
        }
    }
}

/**
 * 能力画像卡: 雷达图只画有证据的维度, 缺的维度用一句话说明, 不拿总平均分凑一个
 * 假画像(计划 §四「画像更新算法」的证据门控思路)。
 */
@Composable
private fun AbilityProfileCard(ability: AbilityAxes, onAssessmentClick: () -> Unit) {
    Card(modifier = Modifier.fillMaxWidth()) {
        Column(
            modifier = Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
            ) {
                Text(
                    text = "能力画像",
                    style = MaterialTheme.typography.titleMedium,
                    modifier = Modifier.weight(1f, fill = false)
                )
                // TODO(P7): CEFR 徽章读 GET /ability 的 cefr_level; 现在还没有定级数据。
                LevelPill("未测评")
            }
            RadarChart(
                values = ability.radarValues(),
                axes = AbilityAxes.LABELS,
                modifier = Modifier.fillMaxWidth()
            )
            when {
                ability.isEmpty -> InlineEmptyState(
                    text = "还没有可统计的练习。先完成一次跟读或情景课, 这里会长出你的雷达图。"
                )
                !ability.isComplete -> InlineEmptyState(
                    text = ability.missingLabels().joinToString("、") +
                        " 还没有数据, 完成一次测评即可补全画像。"
                )
            }
            if (!ability.isComplete) {
                TextButton(onClick = onAssessmentClick) {
                    Text("去测评, 解锁完整四维画像")
                }
            }
        }
    }
}

/** 原 Dashboard 的统计区块, 平移到我的 Tab(逻辑未改)。 */
@Composable
private fun PracticeSummary(stats: PracticeStats) {
    if (!stats.hasData) {
        InlineEmptyState(
            text = "还没有练习记录。完成第一次跟读或自由对话后, 这里会显示总次数、平均分和连续天数。"
        )
        return
    }
    TopStatsRow(stats = stats)
    StreakCard(streakDays = stats.streakDays, recentSessions = stats.recentSessions)
    TrendCard(daily = stats.daily)
    SubjectBreakdownCard(stats = stats)
}
