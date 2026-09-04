package com.app.english.ui.theme

import androidx.compose.ui.graphics.Color

// Feedback colors per spec §5.3 — semantic score bands, do NOT re-theme:
// GREEN >= 85, YELLOW >= 60, RED < 60 (see domain/ScoreColorMapper).
val ScoreGreen = Color(0xFF2E7D32)
val ScoreYellow = Color(0xFFF9A825)
val ScoreRed = Color(0xFFC62828)

// ---------------------------------------------------------------------------
// v2.0 「可栗」chestnut/cream palette — plan §6.2 token table, light + dark.
// The hex values below are the contract with the design spec; change them only
// by changing §6.2 first.
// ---------------------------------------------------------------------------

// ---- Light palette ----
// primary 0xFFB4552D 栗棕: primary actions, record button, progress.
val Primary = Color(0xFFB4552D)
val OnPrimary = Color(0xFFFFFFFF)
val PrimaryContainer = Color(0xFFF6DCCE)
val OnPrimaryContainer = Color(0xFF3E1F0E)

// secondary 0xFF8D6E63: secondary emphasis (chips, muted accents).
val Secondary = Color(0xFF8D6E63)
val OnSecondary = Color(0xFFFFFFFF)
val SecondaryContainer = Color(0xFFEDE0D9)
val OnSecondaryContainer = Color(0xFF26170F)

// tertiary 0xFFFFB74D 暖橙: score highlights, badges.
val Tertiary = Color(0xFFFFB74D)
val OnTertiary = Color(0xFF3E2500)
val TertiaryContainer = Color(0xFFFFE7C2)
val OnTertiaryContainer = Color(0xFF4A2C00)

// surface 白 cards, background 奶油白 page bed.
val Surface = Color(0xFFFFFFFF)
val OnSurface = Color(0xFF1C1613)
val SurfaceVariant = Color(0xFFF5E9DF)
val OnSurfaceVariant = Color(0xFF53423A)
val Background = Color(0xFFFFF8F2)
val OnBackground = Color(0xFF1C1613)
val SurfaceContainer = Color(0xFFF7EDE4)
val ErrorLight = Color(0xFFBA1A1A)
val OnErrorLight = Color(0xFFFFFFFF)
val ErrorContainerLight = Color(0xFFFFDAD6)
val OnErrorContainerLight = Color(0xFF410002)
val OutlineLight = Color(0xFF8F7D73)
val OutlineVariantLight = Color(0xFFE2D2C6)

// ---- Dark palette ----
// primary 0xFFE8B48F on deep chestnut; same roles as light.
val PrimaryDark = Color(0xFFE8B48F)
val OnPrimaryDark = Color(0xFF3E1F0E)
val PrimaryContainerDark = Color(0xFF5C3620)
val OnPrimaryContainerDark = Color(0xFFF9DCCC)
val SecondaryDark = Color(0xFFD7C1B5)
val OnSecondaryDark = Color(0xFF3C2A21)
val SecondaryContainerDark = Color(0xFF544136)
val OnSecondaryContainerDark = Color(0xFFEDDFD6)
val TertiaryDark = Color(0xFFFFCC80)
val OnTertiaryDark = Color(0xFF442900)
val TertiaryContainerDark = Color(0xFF6A4500)
val OnTertiaryContainerDark = Color(0xFFFFE7C2)

// surface 0xFF28211C cards, background 0xFF1C1613 page bed.
val SurfaceDark = Color(0xFF28211C)
val OnSurfaceDark = Color(0xFFEDE1D9)
val SurfaceVariantDark = Color(0xFF3A2F28)
val OnSurfaceVariantDark = Color(0xFFD3BFB3)
val BackgroundDark = Color(0xFF1C1613)
val OnBackgroundDark = Color(0xFFEDE1D9)
val SurfaceContainerDark = Color(0xFF221C17)
val ErrorDark = Color(0xFFFFB4AB)
val OnErrorDark = Color(0xFF690005)
val ErrorContainerDark = Color(0xFF93000A)
val OnErrorContainerDark = Color(0xFFFFDAD6)
val OutlineDark = Color(0xFF9E8B80)
val OutlineVariantDark = Color(0xFF51453D)

// ---- Scene gallery category accents (plan §6.1: colored 2-col category cards)
// Warm family only — picked off the §6.2 palette so the grid never fights the
// brand; the `on` colors are the ink used on top of each accent.
val SceneDailyColor = Color(0xFFB4552D)
val SceneWorkplaceColor = Color(0xFF8D6E63)
val SceneExamColor = Color(0xFFC97A20)
val SceneTravelColor = Color(0xFF6E8B6A)
val SceneCardOnColor = Color(0xFFFFFFFF)
