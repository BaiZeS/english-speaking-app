package com.app.english.ui.me

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Arrangement
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.ArrowBack
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import com.app.english.domain.model.ABILITY_DIMENSIONS
import com.app.english.domain.model.AbilityProfile
import com.app.english.domain.model.abilityDimensionLabel
import com.app.english.ui.components.ErrorState
import com.app.english.ui.components.LoadingState
import com.app.english.ui.components.RadarChart
import com.app.english.ui.components.SegmentedTabs
import com.app.english.ui.theme.Spacings

/**
 * 完整能力画像页(计划 §6.4): 雷达 + CEFR 徽章 + 锁带提示 + 7/30/90 轨迹。
 * 与「我的」Tab 的画像卡共用 [RadarChart] 与 [AbilityAxes]; 轨迹折线手绘 Canvas,
 * 零图表依赖, 数学在 [TrajectoryMath]。
 */

/** 轨迹分段切换的 UI 选项(顺序与 [DAY_VALUES] 一一对应, 后端只收 7/30/90)。 */
private val DAY_OPTIONS = listOf("近 7 天", "近 30 天", "近 90 天")
private val DAY_VALUES = listOf(7, 30, 90)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AbilityProfileScreen(
    onBack: () -> Unit,
    modifier: Modifier = Modifier,
    viewModel: AbilityProfileViewModel = hiltViewModel()
) {
    val state by viewModel.state.collectAsStateWithLifecycle()
    Scaffold(
        modifier = modifier,
        topBar = {
            TopAppBar(
                title = { Text("能力画像") },
                navigationIcon = {
                    IconButton(onClick = onBack) {
                        Icon(Icons.AutoMirrored.Filled.ArrowBack, contentDescription = "返回")
                    }
                }
            )
        }
    ) { padding ->
        val profile = state.profile
        when {
            state.isLoading && profile == null ->
                LoadingState(modifier = Modifier.padding(padding))

            profile == null -> ErrorState(
                message = state.error ?: "加载画像失败",
                modifier = Modifier.padding(padding),
                onRetry = viewModel::load
            )

            else -> ProfileBody(
                profile = profile,
                selectedDays = state.days,
                onSelectDays = viewModel::selectDays,
                modifier = Modifier
                    .padding(padding)
                    .fillMaxSize()
            )
        }
    }
}

@Composable
private fun ProfileBody(
    profile: AbilityProfile,
    selectedDays: Int,
    onSelectDays: (Int) -> Unit,
    modifier: Modifier = Modifier
) {
    Column(
        modifier = modifier
            .verticalScroll(rememberScrollState())
            .padding(horizontal = Spacings.s3, vertical = Spacings.s2),
        verticalArrangement = Arrangement.spacedBy(Spacings.s3)
    ) {
        CefrCard(profile)
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(Spacings.s3),
                verticalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                Text(text = "四维雷达", style = MaterialTheme.typography.titleMedium)
                RadarChart(
                    values = AbilityAxes.fromProfile(profile).radarValues(),
                    axes = AbilityAxes.LABELS,
                    modifier = Modifier.fillMaxWidth()
                )
                // §6.4「各维度样本数」: 一维一行, 有分显分, null 显空态而不是 0 分。
                ABILITY_DIMENSIONS.forEach { dimension ->
                    val score = profile.dimension(dimension)
                    Row(
                        modifier = Modifier.fillMaxWidth(),
                        horizontalArrangement = Arrangement.spacedBy(Spacings.s2)
                    ) {
                        Text(
                            text = abilityDimensionLabel(dimension),
                            style = MaterialTheme.typography.bodyMedium,
                            modifier = Modifier.weight(1f)
                        )
                        Text(
                            text = score?.let { "${it.toInt()} 分" } ?: "还没有证据 · 练一轮就有",
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (score == null) {
                                MaterialTheme.colorScheme.onSurfaceVariant
                            } else {
                                MaterialTheme.colorScheme.primary
                            }
                        )
                        Text(
                            text = "n=${profile.sampleCount(dimension)}",
                            style = MaterialTheme.typography.labelMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
                val noEvidence = ABILITY_DIMENSIONS.filter { profile.lacksEvidence(it) }
                if (noEvidence.isNotEmpty()) {
                    Text(
                        text = noEvidence.joinToString("、") { abilityDimensionLabel(it) } +
                            " 还没有计入证据: 练一轮就有。",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
        }
        Card(modifier = Modifier.fillMaxWidth()) {
            Column(
                modifier = Modifier.padding(Spacings.s3),
                verticalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                Text(text = "轨迹", style = MaterialTheme.typography.titleMedium)
                SegmentedTabs(
                    options = DAY_OPTIONS,
                    selectedIndex = DAY_VALUES.indexOf(selectedDays).coerceAtLeast(0),
                    onSelect = { index -> onSelectDays(DAY_VALUES[index]) }
                )
                TrajectoryCard(profile)
            }
        }
    }
}

@Composable
private fun CefrCard(profile: AbilityProfile) {
    Card(
        modifier = Modifier.fillMaxWidth(),
        colors = if (profile.isAssessed) {
            CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.primaryContainer)
        } else {
            CardDefaults.cardColors()
        }
    ) {
        Column(
            modifier = Modifier.padding(Spacings.s3).fillMaxWidth(),
            horizontalAlignment = Alignment.CenterHorizontally,
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            Surface(
                shape = RoundedCornerShape(50),
                color = if (profile.isAssessed) {
                    MaterialTheme.colorScheme.primary
                } else {
                    MaterialTheme.colorScheme.outlineVariant
                }
            ) {
                Text(
                    // 后端口径: cefr_level 测评前恒 null —— derived_level 是四维分映射的
                    // 辅助提示, 不放进大徽章冒充官方等级(ability.py 的 resolve_level 同语义)。
                    text = profile.cefrLevel ?: "未测评",
                    style = MaterialTheme.typography.displaySmall,
                    color = if (profile.isAssessed) {
                        MaterialTheme.colorScheme.onPrimary
                    } else {
                        MaterialTheme.colorScheme.onSurfaceVariant
                    },
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(horizontal = Spacings.s4, vertical = Spacings.s1)
                )
            }
            Text(
                text = if (profile.isAssessed) {
                    "CEFR " + (profile.assessmentCefr ?: "") + " · 权威定级来自测评"
                } else {
                    "完成一次测评就会点亮你的 CEFR 等级"
                },
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            if (!profile.isAssessed && profile.derivedLevel != null) {
                Text(
                    text = "按四维分的参考档位: ${profile.derivedLevel}(非官方定级)",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            if (profile.bandLocked) {
                Text(
                    text = "已按测评锁带: 四维等级最多 ±1 档浮动",
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.primary
                )
            }
        }
    }
}

/** 轨迹折线: 四维四条线, null 断线; 空数据给「练一轮就有」。 */
@Composable
private fun TrajectoryCard(profile: AbilityProfile) {
    val lines = TrajectoryMath.segmentsByDimension(profile.trajectory)
    val hasAnyPoint = lines.values.any { it.isNotEmpty() }
    if (!hasAnyPoint) {
        Text(
            text = "近 ${profile.days} 天还没有轨迹: 练一轮就有。",
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        return
    }
    val colors = trajectoryColors()
    val gridColor = MaterialTheme.colorScheme.outlineVariant
    Canvas(
        modifier = Modifier
            .fillMaxWidth()
            .height(140.dp)
    ) {
        // 横向网格线(25/50/75%), 与首页 TrendChart 同一套底纹。
        for (i in 1..3) {
            drawLine(
                color = gridColor,
                start = Offset(0f, size.height * i / 4f),
                end = Offset(size.width, size.height * i / 4f),
                strokeWidth = 1f
            )
        }
        ABILITY_DIMENSIONS.forEachIndexed { dimIndex, dimension ->
            val color = colors[dimIndex % colors.size]
            lines[dimension].orEmpty().forEach { segment ->
                val points = segment.map { point ->
                    Offset(point.x * size.width, (1f - point.y) * size.height)
                }
                if (points.size >= 2) {
                    val path = Path().apply {
                        moveTo(points.first().x, points.first().y)
                        points.drop(1).forEach { lineTo(it.x, it.y) }
                    }
                    drawPath(path = path, color = color, style = Stroke(width = 4f))
                }
                points.forEach { drawCircle(color = color, radius = 4f, center = it) }
            }
        }
    }
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s2)
    ) {
        ABILITY_DIMENSIONS.forEachIndexed { index, dimension ->
            Row(verticalAlignment = Alignment.CenterVertically) {
                Surface(
                    shape = RoundedCornerShape(50),
                    color = colors[index % colors.size],
                    modifier = Modifier.size(10.dp)
                ) {}
                Text(
                    text = abilityDimensionLabel(dimension),
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.padding(start = Spacings.tiny)
                )
            }
        }
    }
}

@Composable
private fun trajectoryColors(): List<Color> = listOf(
    MaterialTheme.colorScheme.primary,
    MaterialTheme.colorScheme.tertiary,
    MaterialTheme.colorScheme.secondary,
    MaterialTheme.colorScheme.error
)
