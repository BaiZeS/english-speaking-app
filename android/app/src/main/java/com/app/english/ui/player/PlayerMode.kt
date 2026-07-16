package com.app.english.ui.player

/**
 * Practice mode for the player screen.
 *
 * - READ_ALONG: all lines from every role are flattened into one sequence.
 *   The user reads each line in order without role distinction.
 *
 * - DIALOGUE: the user picks a role (A or B) and follows only that role's
 *   lines. This is the original NCE role-based practice flow.
 *
 * The wire format is lowercase (e.g. "read_along"), used in navigation
 * arguments so deep links / future API hooks stay stable.
 */
enum class PlayerMode(val wire: String) {
    READ_ALONG("read_along"),
    DIALOGUE("dialogue");

    companion object {
        fun fromWire(value: String?): PlayerMode =
            entries.firstOrNull { it.wire == value } ?: READ_ALONG
    }
}
