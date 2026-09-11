@file:Suppress("MatchingDeclarationName") // Compose 文件: 顶层入口是 @Composable 卡片, carrier 类次之

package com.app.english.ui.scenes

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.Button
import androidx.compose.material3.Card
import androidx.compose.material3.CardDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.style.TextDecoration
import com.app.english.domain.ScoreColorMapper
import com.app.english.domain.model.DrillGradeResult
import com.app.english.ui.components.ScoreBadge
import com.app.english.ui.player.SubScorePill
import com.app.english.ui.player.WordChip
import com.app.english.ui.theme.Spacings
import com.app.english.ui.theme.color

/**
 * 打基础每一步作答之后的**完整**反馈(问题 4)。
 *
 * 后端的 [DrillGradeResult] 本来就把五维子分、逐词分数 + IPA、引擎实际听到的转写、中文
 * 建议一起发下来了, 旧的 `GradeResultCard` 只画总分 + 建议 + 要点, 其余全部丢掉 —— 而更
 * 糟的是那张卡在**过关时根本不出现**(渲染门键在 `answeredStepId == spec.id`, 而产生评分
 * 的那次归约同时把 `spec` 换成了下一题)。现在门只看 `pendingGrade`。
 *
 * 原子件是**复用**而不是重造: 子分胶囊 [SubScorePill]、逐词芯片 [WordChip]、总分
 * [ScoreBadge] 与 [ScoreColorMapper] 配色都来自播读页那一套。但**不整体套用 `ScorePanel`**:
 * 它的形参是 legacy `/score` 的 [com.app.english.domain.model.ScoreResult](三维非空
 * Double), 接不到本步的五维可空分数, 而且把"得分低于 60, 请重录一次后再继续"这类话术写
 * 死在组件里 —— 本步的及格线是服务端给的 `pass_score`, 未必是 60。
 */

/**
 * [DrillFeedbackCard] 的入参。
 *
 * 形参平铺会顶到 detekt 的 `LongParameterList`(这一屏是 grade + 两个旗标 + 两个动作 +
 * modifier), 所以像 `HoldToTalkRowUi` 那样收进一个 carrier。detekt 的"文件名跟着唯一
 * 顶层类"规则不认识 @Composable 入口, 对文件本身关掉 —— 文件名跟着屏幕上那张卡。
 */
class DrillFeedbackUi(
    val grade: DrillGradeResult,
    /**
     * 这一步服务端还允许再答(不及格留在 pending)时才给「再试一次」。
     * 已过关的步再提交只会吃 409 `STEP_ALREADY_DONE`, 摆一个必然报错的按钮是假选项。
     */
    val canRetry: Boolean,
    /** 自动前进提示; 空串 = 手动继续, 不画这一行。 */
    val autoAdvanceHint: String,
    val onRetry: () -> Unit,
    val onContinue: () -> Unit
)

@Composable
fun DrillFeedbackCard(feedback: DrillFeedbackUi, modifier: Modifier = Modifier) {
    val grade = feedback.grade
    Card(
        modifier = modifier.fillMaxWidth(),
        colors = CardDefaults.cardColors(
            containerColor = if (grade.passed && !grade.isSkipped) {
                MaterialTheme.colorScheme.primaryContainer
            } else {
                MaterialTheme.colorScheme.errorContainer
            }
        )
    ) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .padding(Spacings.s2),
            verticalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            if (grade.isSkipped) {
                // 跳过没有评分证据。那枚服务端为了复用响应形状而填的 0 分一旦被画出来,
                // 旁边还跟着 passed=true 的"过关" —— 是把"没做"说成"做得很差"。
                Text("已跳过这一步", style = MaterialTheme.typography.titleMedium)
                if (grade.feedbackCn.isNotBlank()) {
                    Text(grade.feedbackCn, style = MaterialTheme.typography.bodyMedium)
                }
                Text(
                    text = "跳过不评分, 也不计入能力画像",
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            } else {
                ScoreHeader(grade)
                GradeDetails(grade)
            }
            FeedbackActions(feedback)
        }
    }
}

/** 分数、逐词、转写、建议、要点、误译 —— 引擎给出的 everything else。 */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun GradeDetails(grade: DrillGradeResult) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.s1)) {
        if (!grade.isRealEvidence) {
            Text(
                text = "本轮为离线占位评分 (${grade.source}), 不计入能力画像",
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.tertiary
            )
        }
        val subScores = drillSubScoreReadout(grade)
        if (subScores.isNotEmpty()) {
            // 只画有证据的维度: null 是"这一轮没测到", 补成 0 就是白扣一个分。
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(Spacings.tiny)
            ) {
                subScores.forEach { dim ->
                    SubScorePill(dim.label, dim.score, Modifier.weight(1f))
                }
            }
        }
        if (grade.wordDetails.isNotEmpty()) {
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                SectionLabel("逐词得分")
                FlowRow(
                    horizontalArrangement = Arrangement.spacedBy(Spacings.half),
                    verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
                ) {
                    grade.wordDetails.forEach { word ->
                        WordChip(
                            word = word.word,
                            scoreColor = ScoreColorMapper.level(word.score).color(),
                            score = word.score,
                            ipa = word.ipa
                        )
                    }
                }
            }
        }
        grade.transcript?.takeIf { it.isNotBlank() }?.let { heard ->
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                SectionLabel("引擎听到")
                Text(
                    text = heard,
                    style = MaterialTheme.typography.bodyMedium,
                    fontStyle = FontStyle.Italic
                )
            }
        }
        if (grade.feedbackCn.isNotBlank()) {
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                SectionLabel("建议")
                Text(grade.feedbackCn, style = MaterialTheme.typography.bodyMedium)
            }
        }
        grade.keyPointsHit.forEach { hit ->
            Text(
                text = "✓ $hit",
                style = MaterialTheme.typography.bodySmall,
                color = MaterialTheme.colorScheme.tertiary
            )
        }
        grade.mistakes.forEach { mistake ->
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                Text(
                    text = mistake.said,
                    style = MaterialTheme.typography.bodySmall,
                    textDecoration = TextDecoration.LineThrough,
                    color = MaterialTheme.colorScheme.error
                )
                Text(
                    text = "${mistake.better} — ${mistake.explanationCn}",
                    style = MaterialTheme.typography.bodySmall,
                    color = MaterialTheme.colorScheme.tertiary
                )
            }
        }
    }
}

@Composable
private fun ScoreHeader(grade: DrillGradeResult) {
    Row(
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
    ) {
        ScoreBadge(score = grade.score)
        Text(
            text = if (grade.passed) "过关" else "未到 ${grade.passScore.toInt()} 分, 可以再试一次",
            style = MaterialTheme.typography.titleMedium,
            color = if (grade.passed) {
                MaterialTheme.colorScheme.onPrimaryContainer
            } else {
                MaterialTheme.colorScheme.error
            }
        )
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(
        text = text,
        style = MaterialTheme.typography.labelMedium,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
}

/**
 * 两个出口 + 一行低调的倒计时提示。
 *
 * 「再试一次」只在还能再答时出现(见 [DrillFeedbackUi.canRetry]); 「继续」在过关时把屏幕
 * 交给下一题, 在未过关时只是撤掉停留 —— 步还留在原地, 录音键就在下面。
 */
@Composable
private fun FeedbackActions(feedback: DrillFeedbackUi) {
    Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(Spacings.s1)
        ) {
            if (feedback.canRetry) {
                OutlinedButton(
                    onClick = feedback.onRetry,
                    modifier = Modifier.weight(1f)
                ) { Text("再试一次") }
            }
            Button(
                onClick = feedback.onContinue,
                modifier = Modifier.weight(1f)
            ) { Text("继续") }
        }
        if (feedback.autoAdvanceHint.isNotBlank()) {
            // 小字 + 半透明(`labelSmall` + `onSurfaceVariant` 五成不透明度): 这行的作用
            // 只是"待会儿它会自己走", 绝不能和反馈正文抢视觉权重。
            Text(
                text = feedback.autoAdvanceHint,
                style = MaterialTheme.typography.labelSmall,
                color = MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = HINT_TEXT_ALPHA)
            )
        }
    }
}

/** 提示行只降不透明度, 字重与正文同源。 */
private const val HINT_TEXT_ALPHA = 0.5f
