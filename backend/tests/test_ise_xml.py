from __future__ import annotations

import pytest

from app.services.ise_xml import parse_ise_xml

# 真实 ISE 评测返回 XML 的精简片段 (read_sentence / ent=en).
# word hello: 2 syllables (hh ax, l ow), total_score 2.88 -> 57.6/100
# word sil: 静音标记, 必须跳过
# word world: 1 syllable (w er l d), total_score 3.89 -> 77.8/100
_SAMPLE_XML = """\
<rec_paper>
  <read_chapter total_score="4.166970" word_count="6">
    <sentence total_score="4.166970">
      <word content="hello" total_score="2.880702" dp_message="0">
        <syll content="hh ax" syll_score="2.369673">
          <phone content="hh" dp_message="0"/>
          <phone content="ax" dp_message="0"/>
        </syll>
        <syll content="l ow" syll_score="3.391732">
          <phone content="l" dp_message="0"/>
          <phone content="ow" dp_message="0"/>
        </syll>
      </word>
      <word content="sil"/>
      <word content="world" total_score="3.890759" dp_message="0">
        <syll content="w er l d" syll_score="3.890759">
          <phone content="w" dp_message="0"/>
          <phone content="er" dp_message="0"/>
          <phone content="l" dp_message="0"/>
          <phone content="d" dp_message="0"/>
        </syll>
      </word>
    </sentence>
  </read_chapter>
</rec_paper>
"""


def test_parses_words_and_skips_sil() -> None:
    recognized, words = parse_ise_xml(_SAMPLE_XML)
    assert recognized == "hello world"
    assert len(words) == 2
    assert [w.word for w in words] == ["hello", "world"]


def test_scores_mapped_to_100() -> None:
    _, words = parse_ise_xml(_SAMPLE_XML)
    # 2.880702 * 20 = 57.61404
    assert words[0].score == pytest.approx(57.61404)
    # 3.890759 * 20 = 77.81518
    assert words[1].score == pytest.approx(77.81518)


def test_ipa_joined_from_syllables() -> None:
    _, words = parse_ise_xml(_SAMPLE_XML)
    assert words[0].ipa == "hh ax l ow"
    assert words[1].ipa == "w er l d"


def test_empty_xml_returns_empty() -> None:
    assert parse_ise_xml("") == ("", [])
    assert parse_ise_xml("   ") == ("", [])


def test_word_without_score_gets_zero() -> None:
    xml = "<rec_paper><word content='hi'/></rec_paper>"
    recognized, words = parse_ise_xml(xml)
    assert recognized == "hi"
    assert words[0].score == 0.0
    assert words[0].ipa is None


def test_scores_clamped_to_100() -> None:
    # ISE 理论上限 5 -> 100, 防御 >5 的异常值
    xml = '<rec_paper><word content="hi" total_score="6.0"/></rec_paper>'
    _, words = parse_ise_xml(xml)
    assert words[0].score == 100.0
