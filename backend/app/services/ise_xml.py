"""解析讯飞 ISE 语音评测返回的 XML 结果.

ISE 评测 (read_sentence / ent=en) 返回的 XML 结构:
  <rec_paper>
    <read_chapter total_score= accuracy_score= fluency_score= integrity_score= word_count=>
      <sentence ...>
        <word content="hello" total_score="2.88" dp_message="0">
          <syll content="hh ax" syll_score="2.37">
            <phone content="hh" dp_message="0"/>
            <phone content="ax" dp_message="0"/>
          </syll>
        </word>
        <word content="sil"/>          <!-- 静音, 跳过 -->
        ...

评分是 1-5 制, 映射到 0-100: score * 20.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from app.services.interfaces import AsrWord

# ISE 评分范围 1-5, 映射到 0-100
_SCORE_SCALE = 20.0
_SIL_CONTENT = "sil"


def _to_100(raw: str | None) -> float:
    """把 ISE 1-5 制分数转 0-100, 夹紧到 [0, 100]. 缺分记 0."""
    if raw is None:
        return 0.0
    try:
        v = float(raw) * _SCORE_SCALE
    except ValueError:
        return 0.0
    return max(0.0, min(100.0, v))


def _word_ipa(word_el: ET.Element) -> str | None:
    """拼接 word 下所有 syll 的 phoneme (如 "hh ax l ow"). 无 syll 返回 None."""
    phonemes: list[str] = []
    for syll in word_el.iter("syll"):
        content = syll.get("content", "").strip()
        if content:
            phonemes.extend(content.split())
    return " ".join(phonemes) if phonemes else None


def parse_ise_xml(xml: str) -> tuple[str, list[AsrWord]]:
    """解析 ISE 结果 XML, 返回 (recognized, word_scores).

    recognized: 非 sil 的 word content 用空格拼接 (供 score_read_along 算完整度/对齐).
    word_scores: 每个 AsrWord(word 小写, score 0-100, ipa 或 None), 按 XML 出现顺序.
    """
    if not xml.strip():
        return "", []
    root = ET.fromstring(xml)
    words: list[AsrWord] = []
    contents: list[str] = []
    for word_el in root.iter("word"):
        content = word_el.get("content", "").strip()
        if not content or content == _SIL_CONTENT:
            continue
        score = _to_100(word_el.get("total_score"))
        words.append(AsrWord(word=content.lower(), score=score, ipa=_word_ipa(word_el)))
        contents.append(content.lower())
    return " ".join(contents), words
