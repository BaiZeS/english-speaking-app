package com.app.english.domain.model

/** 一轮的输入形态。后端只认这两个值; 语音走讯飞 `zh_cn` 中英混读听写, 文字不经听写。 */
object TurnMode {
    const val VOICE = "voice"
    const val TEXT = "text"
}
