package com.app.english.update

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class SemVerTest {
    @Test
    fun compare_equalVersions_returnsZero() {
        assertEquals(0, SemVer.compare("1.2.3", "1.2.3"))
        assertEquals(0, SemVer.compare("1.0.0", "1.0.0-rc1"))
        assertEquals(0, SemVer.compare("0.0.1", "0.0.1"))
    }

    @Test
    fun compare_higherPatchIsNewer() {
        assertTrue(SemVer.isNewer("1.0.1", "1.0.0"))
        assertFalse(SemVer.isNewer("1.0.0", "1.0.1"))
    }

    @Test
    fun compare_higherMinorIsNewer() {
        assertTrue(SemVer.isNewer("1.2.0", "1.1.9"))
    }

    @Test
    fun compare_higherMajorIsNewer() {
        assertTrue(SemVer.isNewer("2.0.0", "1.99.99"))
        assertTrue(SemVer.isOlder("1.99.99", "2.0.0"))
    }

    @Test
    fun compare_handlesMissingComponents() {
        assertTrue(SemVer.isNewer("1.2", "1.1.99"))
        assertTrue(SemVer.isOlder("1.1", "1.1.1"))
    }

    @Test
    fun compare_ignoresNonNumericSuffix() {
        // "1.0.0-rc.1" -> 1.0.0 after stripping suffix
        assertEquals(0, SemVer.compare("1.0.0", "1.0.0-rc.1"))
    }
}
