"""validate_embeddings.py 단위 테스트."""

import gzip
import json
import tempfile
from pathlib import Path

from mlops.scripts.validate_embeddings import validate_jsonl


def _make_jsonl(records: list[dict]) -> Path:
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return tmp


def _ok_record(**overrides) -> dict:
    base = {
        "chunk_index": 0,
        "paper_pmid": "12345",
        "paper_title": "T",
        "section_name": "Methods",
        "token_count": 400,
        "search_categories": ["resistance_training"],
        "paper_doi": "10.1/abc",
        "publication_types": ["Randomized Controlled Trial"],
        "evidence_weight": 0.9,
        "fulltext_source": "pmc",
        "published_year": 2018,
        "embedding": [0.1] * 1024,
    }
    base.update(overrides)
    return base


def test_pass_when_all_thresholds_met():
    """모든 임계 충족 → schema_ok=True, identifier_fill_rate=1.0."""
    # 다양한 evidence_weight + 충분한 paper count for chunks_per_paper
    weights = [0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0]
    types_list = [
        ["Case Reports"],
        ["Review"],
        ["Journal Article"],
        ["Cohort Study"],
        ["Clinical Trial"],
        ["Randomized Controlled Trial"],
        ["Meta-Analysis"],
    ]
    # 5 papers × 25 chunks = 125 chunks (chunks/paper avg = 25, in [20,60])
    records = []
    for p in range(5):
        for c in range(25):
            i = p * 25 + c
            records.append(
                _ok_record(
                    chunk_index=c,
                    paper_pmid=f"pmid{p}",
                    paper_doi=f"10.1/paper{p}",
                    evidence_weight=weights[i % len(weights)],
                    publication_types=types_list[i % len(types_list)],
                    fulltext_source="local_pdf" if p == 0 else "pmc",
                    token_count=400,
                )
            )
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert result.schema_ok, f"missing: {result.missing_keys}"
    assert result.identifier_fill_rate == 1.0
    assert result.publication_types_fill_rate == 1.0
    assert result.embedding_dim == 1024


def test_fail_when_key_missing():
    rec = _ok_record()
    rec.pop("publication_types")
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert not result.schema_ok
    assert "publication_types" in result.missing_keys


def test_fail_when_identifier_missing():
    """둘 다 빈 청크가 있으면 identifier_fill_rate < 1."""
    rec = _ok_record(paper_doi="", paper_pmid="")
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert result.identifier_fill_rate < 1.0
    assert not result.passed


def test_pmid_only_still_passes_identifier():
    """paper_doi 비어있어도 paper_pmid 있으면 identifier coverage 100%."""
    rec = _ok_record(paper_doi="", paper_pmid="9999")
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert result.identifier_fill_rate == 1.0


def test_fail_when_publication_types_under_threshold():
    """publication_types 빈 비율이 10% 초과 → FAIL."""
    records = []
    for i in range(100):
        rec = _ok_record(chunk_index=i, paper_pmid=f"p{i // 5}", paper_doi=f"10.1/{i // 5}")
        if i < 20:  # 20% 빈 → 80% filled, 90% 임계 미달
            rec["publication_types"] = []
        records.append(rec)
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert result.publication_types_fill_rate < 0.90
    assert not result.passed


def test_fail_when_avg_token_out_of_range():
    """평균 토큰 100 → AVG_TOKEN_MIN(300) 미달."""
    records = [_ok_record(chunk_index=i, token_count=100, paper_pmid=f"p{i // 5}") for i in range(20)]
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert not result.passed
    assert result.avg_token < 300


def test_embedding_dim_mismatch():
    rec = _ok_record(embedding=[0.1] * 512)  # bge-base 차원
    path = _make_jsonl([rec])
    result = validate_jsonl([path])
    assert not result.passed
    assert result.embedding_dim != 1024


def test_pdf_subset_avg_calculated():
    """fulltext_source='local_pdf' 청크의 평균 토큰만 별도 추적."""
    records = [
        _ok_record(chunk_index=0, fulltext_source="local_pdf", token_count=200),
        _ok_record(chunk_index=1, fulltext_source="local_pdf", token_count=200),
        _ok_record(chunk_index=2, fulltext_source="pmc", token_count=400),
    ]
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert 150 <= result.pdf_avg_token <= 250


def test_evidence_weight_05_ratio_caught():
    """evidence_weight가 거의 다 0.5 → 0.5 ratio > 50% → FAIL."""
    records = [_ok_record(chunk_index=i, paper_pmid=f"p{i // 5}", evidence_weight=0.5) for i in range(100)]
    path = _make_jsonl(records)
    result = validate_jsonl([path])
    assert result.evidence_weight_05_ratio >= 0.50
    assert not result.passed
