"""JATS nested <sec> 추출 회귀 테스트.

문제: body.findall('.//sec') 가 descendant-or-self라
      부모 Methods sec + 자식 Subjects/Procedure/Statistics 각각이
      별개 PaperSection으로 추출됨 → 평균 56 토큰 청크의 직접 원인.
"""
from defusedxml import ElementTree as ET2

from mlops.pipeline.crawler import _parse_pmc_sections
from mlops.pipeline.europepmc import parse_sections


JATS_XML = b"""<?xml version="1.0"?>
<article>
  <body>
    <sec>
      <title>Methods</title>
      <p>intro paragraph here describing the methodology.</p>
      <sec>
        <title>Subjects</title>
        <p>50 trained males with at least one year of resistance training experience.</p>
      </sec>
      <sec>
        <title>Procedure</title>
        <p>Subjects performed three sets of bench press at 75% 1RM.</p>
      </sec>
      <sec>
        <title>Statistics</title>
        <p>Two-way ANOVA with repeated measures was applied.</p>
      </sec>
    </sec>
    <sec>
      <title>Results</title>
      <p>Significant increases were observed across all groups.</p>
    </sec>
  </body>
</article>"""


def test_parse_sections_emits_top_level_only():
    """Top-level <sec>만 추출되어야 함 (현재 버그는 4+1=5개 emit)."""
    sections = parse_sections(JATS_XML)
    names = [s.name for s in sections]
    assert names == ["Methods", "Results"], f"Expected top-level only, got: {names}"


def test_parse_sections_methods_includes_subsection_content():
    """Methods 섹션은 intro paragraph + 모든 sub-sec text를 포함."""
    sections = parse_sections(JATS_XML)
    methods = next(s for s in sections if s.name == "Methods")
    # 부모 intro
    assert "intro paragraph" in methods.content
    # 모든 자식 sub-sec text
    assert "50 trained males" in methods.content
    assert "three sets of bench press" in methods.content
    assert "Two-way ANOVA" in methods.content


def test_parse_sections_preserves_subsection_titles():
    """Sub-sec title을 inline heading으로 보존 (정보 손실 방지)."""
    sections = parse_sections(JATS_XML)
    methods = next(s for s in sections if s.name == "Methods")
    # heading은 텍스트 안에 어딘가 보존됨 (e.g. "## Subjects" 또는 prefix)
    assert "Subjects" in methods.content
    assert "Procedure" in methods.content
    assert "Statistics" in methods.content


def test_parse_sections_empty_body():
    assert parse_sections(b"<article><body></body></article>") == []


def test_crawler_uses_same_parser():
    """crawler._parse_pmc_sections도 nested sec 픽스 적용 (코드 중복 해소)."""
    root = ET2.fromstring(JATS_XML)
    sections = _parse_pmc_sections(root)
    names = [s.name for s in sections]
    assert names == ["Methods", "Results"]
