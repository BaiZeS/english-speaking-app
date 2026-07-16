package com.app.english.ui.player

/** The three practice modes exposed by the app. */
enum class PlayerMode(val wire: String) {
    /** Sentence-by-sentence practice with no role distinction. */
    READ_ALONG("read_along"),

    /** A and B alternate; A is played and B is recorded and scored. */
    DIALOGUE("dialogue"),

    /** AI/user conversation with a suggested answer on every turn. */
    FREE_DIALOGUE("free_dialogue");

    companion object {
        fun fromWire(value: String?): PlayerMode =
            entries.firstOrNull { it.wire == value } ?: READ_ALONG
    }
}
