package com.app.english.ui.components

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.AutoAwesome
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.unit.dp
import com.app.english.ui.theme.Spacings

/**
 * 「建议」块 —— 打基础 [com.app.english.ui.scenes.DrillFeedbackCard] / 播读
 * [com.app.english.ui.player.ScorePanel] / 自由对话 FreeScoreCard **三张反馈卡共用的中性词表原子件**
 * 之一: 引擎听写转写 [TranscriptQuotedBlock] 是另一个。
 *
 * 为什么要收成一个: 这三处本来各自手写"建议：" + 一段 bodyMedium 纯文本, 于是同一条
 * LLM 建议在跟读页像正文、在打基础页像卡片里的第二层缩进, 学员分不清"这句是引擎说的"
 * 还是"这句是App要我做的"。块自带标签与底色, 调用点就不再需要"建议："前缀 —— 前缀留在
 * 文案里会和块标签重复。
 *
 * 颜色只用 M3 角色(`tertiaryContainer` / `onTertiaryContainer`), 不碰分数色带: 建议**不是
 * 分数**, 它不该抢绿/黄/红的注意力。
 */
@Composable
fun SuggestionBlock(text: String, modifier: Modifier = Modifier) {
    Surface(
        // 铺满父级宽度是"块"这个定位的一部分: 只包内容的话, 一句短建议会缩成一小坨底色,
        // 和它下面贴边排布的正文对不齐。调用点仍可用 modifier 加 padding / 对齐。
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.tertiaryContainer,
        shape = MaterialTheme.shapes.extraSmall
    ) {
        Row(
            modifier = Modifier.padding(Spacings.s2),
            horizontalArrangement = Arrangement.spacedBy(Spacings.s1),
            verticalAlignment = Alignment.Top
        ) {
            Icon(
                imageVector = Icons.Filled.AutoAwesome,
                contentDescription = null,
                tint = MaterialTheme.colorScheme.onTertiaryContainer,
                modifier = Modifier.size(SUGGESTION_ICON_SIZE)
            )
            Column(verticalArrangement = Arrangement.spacedBy(Spacings.tiny)) {
                Text(
                    text = SUGGESTION_LABEL,
                    style = MaterialTheme.typography.labelMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
                Text(
                    text = text,
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onTertiaryContainer
                )
            }
        }
    }
}

/**
 * 「引擎听到」块: 把 ASR 的实际听写和 App 自己的话分开。
 *
 * 斜体 + 引号式底色是**有意的**: 这一行不是结论, 是原始证据。学员看到"我以为说了
 * relationship, 引擎给的是 relation"才能定位问题, 而 App 的判断混在同样式的正文里就做不
 * 到这件事。转写为空时调用点自己决定不画(见各卡的 `takeIf { isNotBlank() }` 护栏)。
 */
@Composable
fun TranscriptQuotedBlock(
    text: String,
    label: String = TRANSCRIPT_DEFAULT_LABEL,
    modifier: Modifier = Modifier
) {
    Surface(
        modifier = modifier.fillMaxWidth(),
        color = MaterialTheme.colorScheme.surfaceVariant,
        shape = MaterialTheme.shapes.extraSmall
    ) {
        Column(
            modifier = Modifier.padding(
                horizontal = Spacings.s2,
                vertical = TRANSCRIPT_PADDING_VERTICAL
            ),
            verticalArrangement = Arrangement.spacedBy(Spacings.tiny)
        ) {
            Text(
                text = label,
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant
            )
            Text(
                text = text,
                style = MaterialTheme.typography.bodyMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                fontStyle = FontStyle.Italic
            )
        }
    }
}

/**
 * 分数色带做芯片底色时的不透明度: 底色用 18% 的带色, 文字才压得住。
 *
 * `internal` 而不是 `private`: 逐词芯片 [com.app.english.ui.player.WordChip] 要用同一个值 ——
 * 同一套"带色但别吵"的判断在两处必须一致, 复制第二个 0.18f 迟早会漂。
 */
internal const val CHIP_TINT_ALPHA = 0.18f

private const val SUGGESTION_LABEL = "建议"
private const val TRANSCRIPT_DEFAULT_LABEL = "引擎听到"
private val SUGGESTION_ICON_SIZE = 18.dp
private val TRANSCRIPT_PADDING_VERTICAL = 10.dp
