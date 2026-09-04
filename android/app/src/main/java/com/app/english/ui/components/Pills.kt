package com.app.english.ui.components

import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import com.app.english.ui.theme.KeliPillShape
import com.app.english.ui.theme.Spacings

/** CEFR 等级小徽章(A1..C2), 空值不渲染。 */
@Composable
fun LevelPill(
    text: String,
    modifier: Modifier = Modifier,
    containerColor: Color = MaterialTheme.colorScheme.secondaryContainer,
    contentColor: Color = MaterialTheme.colorScheme.onSecondaryContainer
) {
    if (text.isBlank()) return
    Surface(modifier = modifier, shape = KeliPillShape, color = containerColor) {
        Text(
            text = text,
            style = MaterialTheme.typography.labelSmall,
            color = contentColor,
            modifier = Modifier.padding(horizontal = Spacings.s1, vertical = 2.dp)
        )
    }
}

/**
 * 通关徽章 —— false-safe: `cleared` 在后端 `course_progress`(P4)落地前恒为
 * false, 所以未通关时什么都不画, 不画一个灰色的「未通关」占位。
 */
@Composable
fun ClearedBadge(cleared: Boolean, modifier: Modifier = Modifier) {
    if (!cleared) return
    Surface(
        modifier = modifier,
        shape = KeliPillShape,
        color = MaterialTheme.colorScheme.tertiaryContainer
    ) {
        Text(
            text = "已通关",
            style = MaterialTheme.typography.labelSmall,
            color = MaterialTheme.colorScheme.onTertiaryContainer,
            modifier = Modifier.padding(horizontal = Spacings.s1, vertical = 2.dp)
        )
    }
}
