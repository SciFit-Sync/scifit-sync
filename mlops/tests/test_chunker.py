"""chunker 모듈 단위 테스트.

외부 의존성 없이 순수 로직만 테스트한다.
"""

from mlops.pipeline.chunker import chunk_paper, chunk_papers, count_tokens
from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection


def _make_paper(
    pmid: str = "12345",
    title: str = "Test Paper",
    abstract: str = "",
    sections: list[PaperSection] | None = None,
) -> PaperFull:
    return PaperFull(
        meta=PaperMeta(pmid=pmid, title=title, abstract=abstract),
        sections=sections or [],
    )


class TestCountTokens:
    def test_empty_string(self):
        assert count_tokens("") == 0

    def test_simple_text(self):
        tokens = count_tokens("Hello world")
        assert tokens > 0

    def test_longer_text_more_tokens(self):
        short = count_tokens("Short text.")
        long = count_tokens("This is a much longer text with many more words and tokens.")
        assert long > short


class TestChunkPaper:
    def test_empty_paper_no_text(self):
        paper = _make_paper()
        chunks = chunk_paper(paper)
        assert chunks == []

    def test_abstract_only_yields_no_chunks(self):
        """초록만 있고 sections=[]인 경우 — 청크 0개 (abstract fallback 제거)."""
        abstract = "Resistance training improves muscle strength. " * 20
        paper = _make_paper(abstract=abstract)
        chunks = chunk_paper(paper)
        assert chunks == []

    def test_sections_short_no_split(self):
        """섹션이 짧으면 분할하지 않음."""
        sections = [
            PaperSection(name="Introduction", content="This study examines strength training. " * 30),
            PaperSection(name="Methods", content="We recruited 50 participants. " * 30),
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        assert len(chunks) == 2
        assert chunks[0].section_name == "Introduction"
        assert chunks[1].section_name == "Methods"

    def test_long_section_gets_split(self):
        """섹션이 길면 분할."""
        long_content = "Progressive overload is a fundamental principle. " * 200
        sections = [PaperSection(name="Results", content=long_content)]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        assert len(chunks) > 1
        # 모든 청크가 같은 섹션명
        for c in chunks:
            assert c.section_name == "Results"

    def test_chunk_index_sequential(self):
        """chunk_index가 0부터 순차 증가."""
        sections = [
            PaperSection(name="Intro", content="Word " * 200),
            PaperSection(name="Methods", content="Another word " * 200),
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        for i, c in enumerate(chunks):
            assert c.chunk_index == i

    def test_token_count_within_bounds(self):
        """각 청크의 토큰 수가 최대값 이하."""
        long_content = "The effect of resistance training on muscle hypertrophy. " * 300
        sections = [PaperSection(name="Discussion", content=long_content)]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        for c in chunks:
            # 약간의 여유 허용 (문장 경계 조정)
            assert c.token_count <= 600  # max_tokens(512) + 여유

    def test_sections_preferred_over_abstract(self):
        """섹션이 있으면 초록은 무시하고 섹션만 사용."""
        paper = _make_paper(
            abstract="This is the abstract. " * 30,
            sections=[PaperSection(name="Results", content="These are results. " * 30)],
        )
        chunks = chunk_paper(paper)
        assert all(c.section_name == "Results" for c in chunks)

    def test_very_short_section_skipped(self):
        """너무 짧은 섹션 (< min_tokens/3) 은 건너뜀."""
        sections = [
            PaperSection(name="Acknowledgments", content="Thanks."),
            PaperSection(name="Methods", content="We used a randomized controlled trial design. " * 30),
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        section_names = [c.section_name for c in chunks]
        assert "Methods" in section_names

    def test_paper_metadata_preserved(self):
        """청크에 논문 메타데이터가 보존."""
        paper = _make_paper(
            pmid="99999",
            title="My Paper Title",
            sections=[PaperSection(name="Methods", content="Study design content. " * 30)],
        )
        chunks = chunk_paper(paper)
        assert len(chunks) >= 1
        for c in chunks:
            assert c.paper_pmid == "99999"
            assert c.paper_title == "My Paper Title"


class TestChunkPapers:
    def test_multiple_papers(self):
        """복수 논문 일괄 청킹."""
        papers = [
            _make_paper(pmid="1", sections=[PaperSection(name="Intro", content="Paper one content. " * 30)]),
            _make_paper(pmid="2", sections=[PaperSection(name="Intro", content="Paper two content. " * 30)]),
        ]
        chunks = chunk_papers(papers)
        pmids = {c.paper_pmid for c in chunks}
        assert "1" in pmids
        assert "2" in pmids

    def test_empty_list(self):
        chunks = chunk_papers([])
        assert chunks == []

    def test_abstract_only_papers_excluded(self):
        """sections=[]인 논문은 chunk_papers 결과에서 제외."""
        papers = [
            _make_paper(pmid="1", abstract="Only abstract. " * 30),
            _make_paper(pmid="2", sections=[PaperSection(name="Intro", content="Has fulltext. " * 30)]),
        ]
        chunks = chunk_papers(papers)
        pmids = {c.paper_pmid for c in chunks}
        assert "1" not in pmids
        assert "2" in pmids


class TestChunkEvidenceMeta:
    def test_paper_without_fulltext_yields_no_chunks(self):
        """본문 sections=[]인 paper는 abstract가 있어도 청크 0개."""
        meta = PaperMeta(
            pmid="999",
            title="No fulltext paper",
            authors="X",
            journal="Y",
            published_year=2020,
            doi="10.1/abc",
            abstract="A long abstract " * 100,
            search_categories=["volume"],
        )
        paper = PaperFull(meta=meta, sections=[])
        chunks = chunk_paper(paper)
        assert chunks == []

    def test_paper_with_fulltext_propagates_evidence_meta(self):
        """본문 있는 paper의 chunk에 paper_doi/publication_types/evidence_weight/fulltext_source/published_year 전파."""
        meta = PaperMeta(
            pmid="123",
            title="OK",
            authors="",
            journal="",
            published_year=2020,
            doi="10.1/xyz",
            abstract="",
            search_categories=[],
            publication_types=["Randomized Controlled Trial"],
            evidence_weight=0.90,
            fulltext_source="pmc",
        )
        paper = PaperFull(meta=meta, sections=[
            PaperSection(name="Intro", content="Resistance training " * 50),
        ])
        chunks = chunk_paper(paper)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.paper_doi == "10.1/xyz"
        assert chunk.publication_types == ["Randomized Controlled Trial"]
        assert chunk.evidence_weight == 0.90
        assert chunk.fulltext_source == "pmc"
        assert chunk.published_year == 2020
