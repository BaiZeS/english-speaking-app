package com.app.english.ui.theme

import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Shapes
import androidx.compose.ui.graphics.Shape
import androidx.compose.ui.unit.dp

/**
 * Shared corner-radius tokens (plan §6.2: 全局卡片圆角 20dp).
 *
 * [KeliCardShape] is exported because some surfaces (custom tiles, the radar
 * card, gallery cells) are drawn with `Surface`/`Box` rather than `Card` and
 * therefore do not inherit [KeliShapes]. Everything that *is* a `Card` picks the
 * radius up automatically via `MaterialTheme.shapes.medium`.
 */
val KeliCardShape: Shape = RoundedCornerShape(20.dp)

/** Pills: level/est-minutes chips, badges, filter chips that we draw ourselves. */
val KeliPillShape: Shape = RoundedCornerShape(percent = 50)

/** Small inner tiles (stat tiles, inset blocks) sitting inside a card. */
val KeliTileShape: Shape = RoundedCornerShape(12.dp)

val KeliShapes = Shapes(
    extraSmall = RoundedCornerShape(8.dp),
    small = KeliTileShape,
    medium = KeliCardShape,
    large = KeliCardShape,
    extraLarge = RoundedCornerShape(24.dp),
    full = CircleShape
)
