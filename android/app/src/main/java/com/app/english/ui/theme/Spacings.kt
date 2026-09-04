package com.app.english.ui.theme

import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp

/**
 * Global spacing scale (plan §6.2: 8/12/16/24).
 *
 * Use these instead of ad-hoc `8.dp` literals so card padding, list gaps and
 * screen margins stay on one rhythm. `half`/`tiny` exist for icon-to-text
 * nudges only — anything structural should use the four named steps.
 */
object Spacings {
    /** Icon/text nudges inside a row. */
    val tiny: Dp = 4.dp

    /** Half step, for dense chips and badges. */
    val half: Dp = 6.dp

    /** s1 — tight gap between related elements. */
    val s1: Dp = 8.dp

    /** s2 — gap between a card's inner blocks, or chip row spacing. */
    val s2: Dp = 12.dp

    /** s3 — screen padding and the default vertical rhythm between cards. */
    val s3: Dp = 16.dp

    /** s4 — section separation and empty-state breathing room. */
    val s4: Dp = 24.dp
}
