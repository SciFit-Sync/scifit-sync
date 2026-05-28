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

    def test_short_adjacent_sections_merge(self):
        """짧은 인접 섹션들은 누적 병합돼 한 청크로 emit (작은 청크 폭증 방지)."""
        sections = [
            PaperSection(name="Introduction", content="This study examines strength training. " * 30),
            PaperSection(name="Methods", content="We recruited 50 participants. " * 30),
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        # 두 섹션이 합쳐서 ≥ MIN(300) 이며 ≤ MAX(512) 이므로 한 청크로 머저됨
        assert len(chunks) == 1
        # 섹션명에 두 이름 모두 보존
        assert "Introduction" in chunks[0].section_name
        assert "Methods" in chunks[0].section_name

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

    def test_very_short_section_merged_not_dropped(self):
        """아주 짧은 섹션도 인접 섹션과 누적 병합돼 손실 없음 (기존엔 < min/3로 폐기됐음)."""
        sections = [
            PaperSection(name="Acknowledgments", content="Thanks."),
            PaperSection(name="Methods", content="We used a randomized controlled trial design. " * 30),
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        # 섹션명에 Methods가 어딘가에 보존
        assert any("Methods" in c.section_name for c in chunks)
        # Thanks 내용도 폐기되지 않고 어딘가에 흡수됨
        assert any("Thanks" in c.content for c in chunks)

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

    # ── 신규: 섹션 머저 / 잔여 흡수 / JATS류 입력 검증 ──────────────────────────
    def test_many_tiny_sections_accumulate(self):
        """JATS류 작은 섹션이 다수일 때 누적 머저로 청크 수가 크게 줄어든다."""
        # 각 ~30토큰짜리 15개 섹션 = 약 450토큰 분량
        sections = [PaperSection(name=f"Sub{i}", content="A short subsection sentence here. " * 5) for i in range(15)]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        # 15개 섹션이 머저되어 청크 수가 훨씬 적어야 함
        assert len(chunks) <= 3, f"머저가 제대로 안 됨: {len(chunks)}개 청크"
        # 모든 청크가 비어있지 않음
        assert all(c.token_count > 0 for c in chunks)
        # 청크 평균 토큰이 옛 버그(평균 ~55) 대비 충분히 큼
        avg = sum(c.token_count for c in chunks) / len(chunks)
        assert avg >= 100, f"평균 청크 토큰이 너무 작음: {avg}"

    def test_no_tiny_tail_after_split(self):
        """큰 섹션 분할 시 작은 잔여(< MIN/2)는 직전 청크에 흡수돼 미니 잔여 청크 0."""
        # ~530토큰 한 섹션 → 분할 시 [~512, ~88] 예상, 잔여 88은 흡수돼야 함
        long_content = "Progressive overload is a fundamental principle of resistance training. " * 75
        sections = [PaperSection(name="Discussion", content=long_content)]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        # 모든 청크가 의미 있는 크기 — MIN/2(150) 미만 잔여 없음
        for c in chunks:
            assert c.token_count >= 150, f"작은 잔여 청크 발생: token_count={c.token_count}"

    def test_pdf_like_single_full_text_section(self):
        """PDF 경로처럼 'Full Text' 한 섹션 → 청커가 토큰 단위로 깔끔 분할."""
        full_text = "This research investigates exercise physiology principles in depth. " * 300
        sections = [PaperSection(name="Full Text", content=full_text)]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        assert len(chunks) > 1
        # 모든 청크가 충분한 크기
        for c in chunks:
            assert c.token_count >= 150
            assert c.section_name == "Full Text"

    def test_merged_section_name_truncated(self):
        """다수 섹션 머저 시 section_name은 80자 이하로 잘려 메타 비대화 방지."""
        sections = [
            PaperSection(name=f"VeryLongSectionName{i}_With_Extra_Suffix", content="Tiny here. " * 5) for i in range(20)
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        for c in chunks:
            assert len(c.section_name) <= 80, f"section_name 너무 김: {len(c.section_name)}"

    def test_mixed_sizes_jats_like(self):
        """JATS류 혼합 (작은 다수 + 중간 + 큰) 입력의 머저·분할 통합 동작."""
        sections = [
            PaperSection(name="Tiny1", content="Short. " * 5),  # ~10토큰
            PaperSection(name="Tiny2", content="Brief. " * 5),  # ~10토큰
            PaperSection(name="Medium", content="A medium-length paragraph of text. " * 40),  # ~280토큰
            PaperSection(name="Big", content="A larger section content here. " * 150),  # ~900토큰 → split
            PaperSection(name="Tail", content="Closing notes. " * 8),  # ~16토큰
        ]
        paper = _make_paper(sections=sections)
        chunks = chunk_paper(paper)
        # 옛 버그면 5+ 청크 + 마이크로 청크들. 새 로직은 합리적 수준(2~5개).
        assert 1 <= len(chunks) <= 6
        # 평균 청크 크기가 옛 평균(55) 대비 크게 개선
        avg = sum(c.token_count for c in chunks) / len(chunks)
        assert avg >= 200, f"평균 청크 크기 미달: {avg}"
        # 모든 청크가 비어있지 않음
        assert all(c.content.strip() for c in chunks)


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
        paper = PaperFull(
            meta=meta,
            sections=[
                PaperSection(name="Intro", content="Resistance training " * 50),
            ],
        )
        chunks = chunk_paper(paper)
        assert len(chunks) >= 1
        chunk = chunks[0]
        assert chunk.paper_doi == "10.1/xyz"
        assert chunk.publication_types == ["Randomized Controlled Trial"]
        assert chunk.evidence_weight == 0.90
        assert chunk.fulltext_source == "pmc"
        assert chunk.published_year == 2020
