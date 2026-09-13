package com.app.english.ui.player

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Card
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.ScoreResult
import com.app.english.ui.components.CHIP_TINT_ALPHA
import com.app.english.ui.components.ScoreRing
import com.app.english.ui.components.SuggestionBlock
import com.app.english.ui.theme.Spacings
import com.app.english.ui.theme.color

/**
 * Score panel that appears after a recording is submitted.
 *
 * Shows the overall score, the three sub-skill averages, an "I need to re-record"
 * hint if the score is below the advancement threshold, the LLM-generated
 * suggestion, and per-word score chips.
 */

/** Top-level score card: score ring header, sub-skills, suggestion, word chips. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ScorePanel(
    score: ScoreResult,
    needsRerecord: Boolean,
    modifier: Modifier = Modifier,
    hasRecording: Boolean = false,
    onPlayMine: () -> Unit = {},
    onCompare: () -> Unit = {}
) {
    Card(modifier = modifier.fillMaxWidth()) {
        Column(
            Modifier.padding(Spacings.s3),
            verticalArrangement = Arrangement.spacedBy(Spacings.s2)
        ) {
            Row(
                verticalAlignment = Alignment.CenterVertically,
                horizontalArrangement = Arrangement.spacedBy(Spacings.s2)
            ) {
                ScoreRing(score = score.total)
                Text(
                    text = "总分",
                    style = MaterialTheme.typography.titleMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant
                )
            }
            SubScoreRow(score.pronunciation, score.fluency, score.completeness)
            if (score.isStub) {
                Text(
                    text = "⚠ 评分引擎未配置，当前为占位假分",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.error
                )
            }
            if (needsRerecord) {
                Text(
                    text = "得分低于 60，请重录一次后再继续。",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.error
                )
            }
            score.suggestion?.takeIf { it.isNotBlank() }?.let { suggestion ->
                SuggestionBlock(suggestion)
            }
            if (score.wordDetails.isNotEmpty()) {
                Text("单词得分", style = MaterialTheme.typography.titleMedium)
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(Spacings.s1),
                    verticalArrangement = Arrangement.spacedBy(Spacings.s1)
                ) {
                    score.wordDetails.forEach { wordScore ->
                        WordChip(
                            word = wordScore.word,
                            scoreColor = ScoreColorMapper.level(wordScore.score).color(),
                            score = wordScore.score,
                            ipa = wordScore.ipa
                        )
                    }
                }
            }
            if (hasRecording) {
                RecordingReplayRow(onPlayMine = onPlayMine, onCompare = onCompare)
            }
        }
    }
}

/** Replay controls for the retained take of the current line. */
@Composable
private fun RecordingReplayRow(
    onPlayMine: () -> Unit,
    onCompare: () -> Unit,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        TextButton(onClick = onPlayMine) { Text("听我的") }
        TextButton(onClick = onCompare) { Text("对比听") }
    }
}

/** Three-pill row showing pronunciation / fluency / completeness. */
@Composable
fun SubScoreRow(
    pronunciation: Double,
    fluency: Double,
    completeness: Double,
    modifier: Modifier = Modifier
) {
    Row(
        modifier = modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        SubScorePill("发音", pronunciation, Modifier.weight(1f))
        SubScorePill("流利度", fluency, Modifier.weight(1f))
        SubScorePill("完整度", completeness, Modifier.weight(1f))
    }
}

/**
 * 单个子项胶囊: 标签在左、带色分数在右, 底下一条同色的迷你进度条。
 *
 * 以前只有"大号数字 + 小标签", 三个维度并排时看不出**差多少**: 88 和 92 的视觉重量一样,
 * 而 62 和 88 也一样 —— 数字太小, 学员读到的是"三个数字", 不是"我的强弱项"。加一条以
 * 满分为终点的条, 短板才靠形状而不是靠读数被看见。颜色仍只取冻结色带, 不另设色。
 */
@Composable
fun SubScorePill(label: String, value: Double, modifier: Modifier = Modifier) {
    val bandColor = ScoreColorMapper.level(value).color()
    Column(
        modifier = modifier.padding(Spacings.tiny),
        verticalArrangement = Arrangement.spacedBy(PILL_LABEL_GAP)
    ) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.SpaceBetween,
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = value.toInt().toString(),
                style = MaterialTheme.typography.labelLarge,
                fontWeight = FontWeight.Bold,
                color = bandColor
            )
        }
        // 用 lambda 版的 progress(仓库先例: PlayerScreen 的课文进度条)。
        // 没有 `gapSize`: 那个形参要 Material3 1.4+ 才有, 本仓 BOM(2024.10.01)解析到
        // 1.3.1 —— 这条重载只有 progress / modifier / color / trackColor / strokeCap。
        LinearProgressIndicator(
            progress = { (value / SCORE_SCALE).toFloat().coerceIn(NO_PROGRESS, FULL_PROGRESS) },
            modifier = Modifier
                .fillMaxWidth()
                .height(PILL_BAR_HEIGHT)
                .clip(RoundedCornerShape(PILL_BAR_CORNER)),
            color = bandColor,
            trackColor = MaterialTheme.colorScheme.surfaceVariant
        )
    }
}

/**
 * 单词芯片: 一整枚**用带色淡底铺出来的芯片**, 而不是"色点 + 词"。
 *
 * 旧版那枚 10dp 色点在密排的 FlowRow 里几乎看不出颜色差异; 把同一条色带按 [CHIP_TINT_ALPHA]
 * 铺成底, "哪个词红了"就变成了形状层面的信息。词本身改用 onSurface —— 底色已经说了分数,
 * 再给文字上色就是同一件事说两遍, 小字号下还更难读。
 *
 * [score] / [ipa] 用**默认参数**加进来, 而不是另造一个组件: ISE 逐词评测本来就把这两
 * 个值发到了客户端(`WordScore`), 但芯片只画一个词 —— 学员看得见"这个词是红的", 看不
 * 出差在哪个音、扣了几分。默认值同时保住播读页那处只给词的旧调用点。
 */
@Composable
fun WordChip(
    word: String,
    scoreColor: Color,
    modifier: Modifier = Modifier,
    score: Double? = null,
    ipa: String? = null
) {
    Surface(
        shape = RoundedCornerShape(percent = CHIP_CORNER_PERCENT),
        color = scoreColor.copy(alpha = CHIP_TINT_ALPHA),
        modifier = modifier
    ) {
        Row(
            modifier = Modifier.padding(
                horizontal = CHIP_PADDING_HORIZONTAL,
                vertical = CHIP_PADDING_VERTICAL
            ),
            horizontalArrangement = Arrangement.spacedBy(Spacings.half),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Column {
                Text(
                    word,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurface,
                    fontWeight = FontWeight.SemiBold
                )
                ipa?.takeIf { it.isNotBlank() }?.let { pronunciation ->
                    // 服务端给的 IPA 有时自带斜杠, 这里统一补上, 免得出现 //ˈriːd//。
                    Text(
                        text = "/${pronunciation.trim('/', ' ')}",
                        style = MaterialTheme.typography.labelSmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                }
            }
            score?.let { value ->
                Text(
                    text = value.toInt().toString(),
                    style = MaterialTheme.typography.labelSmall,
                    fontWeight = FontWeight.Bold,
                    color = scoreColor
                )
            }
        }
    }
}

private const val SCORE_SCALE = 100.0
private const val NO_PROGRESS = 0f
private const val FULL_PROGRESS = 1f
private const val CHIP_CORNER_PERCENT = 50
private val PILL_LABEL_GAP: Dp = 2.dp
private val PILL_BAR_HEIGHT: Dp = 4.dp
private val PILL_BAR_CORNER: Dp = 2.dp
private val CHIP_PADDING_HORIZONTAL: Dp = 10.dp
private val CHIP_PADDING_VERTICAL: Dp = 5.dp
