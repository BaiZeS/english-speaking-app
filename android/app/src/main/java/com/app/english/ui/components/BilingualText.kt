package com.app.english.ui.components

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.unit.dp

/**
 * 双语渲染的**唯一原子**(计划 §4 表, D4/D5)。
 *
 * 两条不变量, 都是拿界面事故换来的:
 *
 * 1. `secondary.isNullOrBlank()` -> **整行不渲染**。空串在协议层的含义是"后端这一格没有
 *    内容"(LLM 未配置 / 该场景没有英文 / 该轮还没判完), 不是"翻译成了空" —— 于是它绝不
 *    允许被渲染成一行空白、一个 `—`, 更不许客户端补一句机翻。缺字段就是缺字段。
 * 2. [collapsible] 的展开态一定带 [label] 标签(默认「中文」)。英文台词下面跟一行中文,
 *    若不标注, 读者会把它当成"第二句参考回答"——这正是 D4 要求台词英文优先、中文折叠的
 *    理由; 展开后标签必须还在, 否则折叠动作把人从一个歧义带到另一个歧义。
 *
 * [collapsible] = false 时中文**默认可见**(要求学员开口的那句示范句就是这种: 它必须
 * 一眼能懂); = true 时行尾给一颗「译」, 中文收在后面(台词的默认态)。
 */
@Composable
fun BilingualText(
    primary: String,
    secondary: String?,
    label: String = "中文",
    modifier: Modifier = Modifier,
    collapsible: Boolean = false,
    primaryStyle: TextStyle? = null,
    secondaryStyle: TextStyle? = null
) {
    // trim 之后再判空: 后端"空格串"与空串同义, 都不该占一行。
    val translation = secondary?.trim().orEmpty()
    val hasTranslation = translation.isNotEmpty()
    var expanded by remember { mutableStateOf(false) }
    Column(modifier = modifier) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(
                text = primary,
                style = primaryStyle ?: MaterialTheme.typography.bodyLarge,
                modifier = Modifier.weight(1f, fill = false)
            )
            // 没有中文就不给「译」: 一颗点开是空的键比没有键更糟。
            if (collapsible && hasTranslation) {
                TextButton(onClick = { expanded = !expanded }) {
                    Text(
                        text = if (expanded) "收起" else "译",
                        style = MaterialTheme.typography.labelMedium
                    )
                }
            }
        }
        if (hasTranslation && (!collapsible || expanded)) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(top = 2.dp),
                verticalAlignment = Alignment.Top
            ) {
                Text(
                    text = label,
                    style = MaterialTheme.typography.labelSmall,
                    color = MaterialTheme.colorScheme.primary,
                    modifier = Modifier.padding(end = 6.dp)
                )
                Text(
                    text = translation,
                    style = secondaryStyle ?: MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                    modifier = Modifier.weight(1f)
                )
            }
        }
    }
}
