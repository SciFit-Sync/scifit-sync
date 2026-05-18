"""upserter DOI 기반 doc_id + 확장 메타 테스트."""

from mlops.pipeline.models import Chunk
from mlops.pipeline.upserter import _make_doc_id


def test_doc_id_uses_doi_with_safe_chars():
    """DOI가 있으면 /는 _, .은 -로 치환 후 chunk_index를 suffix로 붙인다."""
    chunk = Chunk(
        paper_pmid="123",
        paper_doi="10.1519/JSC.0000000000003456",
        paper_title="t",
        section_name="s",
        chunk_index=0,
        content="x",
        token_count=1,
    )
    doc_id = _make_doc_id(chunk)
    assert "/" not in doc_id
    assert "." not in doc_id
    assert doc_id.startswith("10-1519_JSC-0000000000003456")
    assert doc_id.endswith("_0")


def test_doc_id_falls_back_to_pmid_when_no_doi():
    """DOI 빈 문자열이면 pmid 기반 fallback."""
    chunk = Chunk(
        paper_pmid="999",
        paper_doi="",
        paper_title="t",
        section_name="s",
        chunk_index=2,
        content="x",
        token_count=1,
    )
    doc_id = _make_doc_id(chunk)
    assert doc_id == "999_2"


def test_doc_id_chunk_index_appended():
    """chunk_index가 doc_id 끝에 붙는다."""
    chunk = Chunk(
        paper_pmid="0",
        paper_doi="10.1/x",
        paper_title="t",
        section_name="s",
        chunk_index=42,
        content="x",
        token_count=1,
    )
    doc_id = _make_doc_id(chunk)
    assert doc_id.endswith("_42")
