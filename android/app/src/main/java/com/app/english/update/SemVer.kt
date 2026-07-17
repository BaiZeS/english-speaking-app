package com.app.english.update

/**
 * Minimal SemVer comparator for our ``MAJOR.MINOR.PATCH`` strings.
 *
 * Returns positive when [a] is newer than [b], zero when equal, negative when older.
 * Non-numeric components (e.g. pre-release tags like ``-rc1`` or ``-rc.1``) are
 * stripped before splitting so "1.2.3-rc1" compares equal to "1.2.3". We do not
 * need full SemVer here: the backend ships plain dotted version strings from
 * ``APP_LATEST_VERSION`` / ``APP_MIN_SUPPORTED_VERSION``.
 */
object SemVer {
    fun compare(a: String, b: String): Int {
        val aParts = stripSuffix(a).split('.').map { it.toIntOrNull() ?: 0 }
        val bParts = stripSuffix(b).split('.').map { it.toIntOrNull() ?: 0 }
        val length = maxOf(aParts.size, bParts.size)
        for (i in 0 until length) {
            val left = aParts.getOrElse(i) { 0 }
            val right = bParts.getOrElse(i) { 0 }
            if (left != right) return left - right
        }
        return 0
    }

    fun isNewer(candidate: String, baseline: String): Boolean = compare(candidate, baseline) > 0

    fun isOlder(candidate: String, baseline: String): Boolean = compare(candidate, baseline) < 0

    /** Drop everything from the first dash (``1.2.3-rc1`` → ``1.2.3``). */
    private fun stripSuffix(version: String): String =
        version.substringBefore('-', missingDelimiterValue = version)
}
