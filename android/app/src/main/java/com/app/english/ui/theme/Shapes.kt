package com.app.english.ui.theme

import androidx.compose.foundation.shape.CornerBasedShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.unit.dp

/**
 * Shared corner-radius tokens (plan §6.2: 全局卡片圆角 20dp).
 *
 * Token 类型固定为 [CornerBasedShape](`Shape` 的子类): Material3 `Shapes` 的
 * 五个槽位都要求 CornerBasedShape, 这样 KeliShapes 能直接引用这些 token,
 * 用在 `Surface`/`Card` 的 `shape =`(Shape)参数上也一样成立。
 *
 * [KeliCardShape] is exported because some surfaces (custom tiles, the radar
 * card, gallery cells) are drawn with `Surface`/`Box` rather than `Card` and
 * therefore do not inherit [KeliShapes]. Everything that *is* a `Card` picks the
 * radius up automatically via `MaterialTheme.shapes.medium`.
 */
val KeliCardShape: CornerBasedShape = RoundedCornerShape(20.dp)

/** Pills: level/est-minutes chips, badges, filter chips that we draw ourselves. */
val KeliPillShape: CornerBasedShape = RoundedCornerShape(percent = 50)

/** Small inner tiles (stat tiles, inset blocks) sitting inside a card. */
val KeliTileShape: CornerBasedShape = RoundedCornerShape(12.dp)

val KeliShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = KeliTileShape,
    medium = KeliCardShape,
    large = KeliCardShape,
    extraLarge = RoundedCornerShape(24.dp)
)
