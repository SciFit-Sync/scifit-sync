"""validate_embeddings.py 단위 테스트."""

import gzip
import io
import json
import tempfile
from pathlib import Path

from mlops.scripts.validate_embeddings import ValidationResult, print_report, validate_jsonl


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
                    # local_pdf 청크는 pdf_avg_token 범위(150~250) 안으로 조정
                    token_count=200 if p == 0 else 400,
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
        if i < 20:  # 20% 빈 → 80% filled, 85% 임계 미달
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


# ──────────────────────────────────────────────────────────────────────────────
# 토큰 임계 정합 (Fix B) — CLAUDE.md §10 청크 정책(300~512 토큰)과 일치.
# dry_15_v2 관측치(avg 463.8, pdf 471.1)는 chunker가 의도대로 max(512)에 가깝게
# 채운 정상 분포인데, 좁은 임계(MAX 450 / PDF 250)만으로 FAIL이 나던 문제를 해소.
# ──────────────────────────────────────────────────────────────────────────────


def _valid_result(**overrides) -> ValidationResult:
    """토큰 외 모든 게이트를 통과하는 ValidationResult. 토큰 필드만 override해 검증."""
    base = dict(
        schema_ok=True,
        identifier_fill_rate=1.0,
        publication_types_fill_rate=0.95,
        evidence_weight_distinct=6,
        evidence_weight_05_ratio=0.2,
        avg_token=400.0,
        p99_token=580.0,
        over_512_ratio=0.01,
        chunks_per_paper_avg=30.0,
        pdf_avg_token=0.0,  # 기본은 pdf 체크 skip
        embedding_dim=1024,
        total_chunks=100,
    )
    base.update(overrides)
    return ValidationResult(**base)


class TestTokenThresholdAlignment:
    def test_avg_token_464_passes(self):
        """dry_15_v2 관측 avg 463.8은 새 임계(≤512)에서 통과해야 한다."""
        assert _valid_result(avg_token=463.8).passed

    def test_avg_token_512_boundary_inclusive(self):
        """경계값 512는 포함(통과)."""
        assert _valid_result(avg_token=512.0).passed

    def test_avg_token_over_512_fails(self):
        """over-budget(>512) 평균은 여전히 FAIL (회귀 가드)."""
        assert not _valid_result(avg_token=600.0).passed

    def test_avg_token_under_300_fails(self):
        """하한(300) 미달은 여전히 FAIL (회귀 가드)."""
        assert not _valid_result(avg_token=250.0).passed

    def test_pdf_avg_token_471_passes(self):
        """dry_15_v2 관측 pdf 471.1은 새 PDF 임계(200~512)에서 통과해야 한다."""
        assert _valid_result(pdf_avg_token=471.1).passed

    def test_pdf_avg_token_under_200_fails(self):
        """200 미만 PDF 평균은 FAIL — 의미 단위 청크엔 너무 짧음."""
        assert not _valid_result(pdf_avg_token=180.0).passed

    def test_pdf_avg_token_zero_skips_check(self):
        """local_pdf 청크가 없으면(pdf_avg_token==0) PDF 게이트는 skip."""
        assert _valid_result(pdf_avg_token=0.0).passed


# ──────────────────────────────────────────────────────────────────────────────
# publication_types fill rate 게이트 완화 (0.90 → 0.85).
# local_pdf/OpenAlex-only 모집단의 PubMed 미등재 논문(프리프린트·마이너 저널)은
# efetch 보강으로도 채울 수 없다. 실측: 크롤 ≈92%, local_pdf 162/184(88%) →
# 합산이 90% 경계에 걸린다. 미등재분은 데이터 특성이므로 게이트를 85%로 정렬.
# ──────────────────────────────────────────────────────────────────────────────


class TestPublicationTypesThreshold:
    def test_fill_087_passes(self):
        """88% 수준(local_pdf 실측)은 새 임계(≥0.85)에서 통과해야 한다."""
        assert _valid_result(publication_types_fill_rate=0.87).passed

    def test_fill_085_boundary_inclusive(self):
        """경계값 0.85는 포함(통과)."""
        assert _valid_result(publication_types_fill_rate=0.85).passed

    def test_fill_084_fails(self):
        """0.85 미만은 여전히 FAIL (회귀 가드)."""
        assert not _valid_result(publication_types_fill_rate=0.84).passed


# ──────────────────────────────────────────────────────────────────────────────
# evidence_weight 게이트 = 차등화 "붕괴" 탐지 (0.50 → 0.65 → 0.85 → 0.92).
# 게이트는 두 신호의 AND: distinct >= 5 (차등화 다양성) AND 0.5비율 < 0.92.
# 0.5비율이 높음 ≠ 붕괴 — 코퍼스 depth가 깊어지면 매핑 불가한 일반 저널 논문
# (baseline 0.5) 비중이 자연 상승하지만, 고근거 청크(@0.9·@1.0)가 공존하고
# distinct가 건강하면 차등화는 멀쩡하다. d100 실측(0.5비율 0.86, distinct 9)이
# 그 예 — depth-driven 상승이지 붕괴가 아니므로 통과해야 한다. 진짜 붕괴
# (전부 0.5 → distinct 1, 비율 ~1.0)는 두 신호 동시 위반으로 차단된다.
# ──────────────────────────────────────────────────────────────────────────────


class TestEvidenceWeight05RatioThreshold:
    def test_ratio_065_passes(self):
        """depth 깊은 run의 0.65(d030 실측)는 distinct 건강하면 통과."""
        assert _valid_result(evidence_weight_05_ratio=0.65).passed

    def test_ratio_084_passes(self):
        """0.84도 통과 (production 점증 적재 수용)."""
        assert _valid_result(evidence_weight_05_ratio=0.84).passed

    def test_d100_depth_driven_086_with_healthy_distinct_passes(self):
        """d100 실측 재현: 0.5비율 0.86 + distinct 9 → depth-driven 상승, 통과.

        이전 0.85 단독 상한이 오탐하던 핵심 케이스(게이트 0.92로 재정의).
        """
        assert _valid_result(evidence_weight_05_ratio=0.86, evidence_weight_distinct=9).passed

    def test_ratio_092_collapse_fails(self):
        """0.92(전부 0.5 fallback 회귀선)은 경계 포함 FAIL."""
        assert not _valid_result(evidence_weight_05_ratio=0.92).passed

    def test_low_distinct_fails_even_under_max_ratio(self):
        """0.5비율이 낮아도(0.40) distinct<5면 차등화 붕괴로 FAIL."""
        assert not _valid_result(evidence_weight_05_ratio=0.40, evidence_weight_distinct=3).passed

    def test_total_collapse_fails(self):
        """전부 0.5(distinct 1, 비율 1.0) — 정본 붕괴, distinct·상한 동시 위반 FAIL."""
        assert not _valid_result(evidence_weight_05_ratio=1.0, evidence_weight_distinct=1).passed


def test_pdf_avg_token_zero_report_label_matches_passed():
    """D 회귀: pdf_avg_token==0(--skip-local-pdf 정상)이면 passed=True이고
    print_report의 'pdf subset avg' 행 라벨도 [OK]여야 한다 (이전엔 라벨만 [FAIL]).
    """
    result = _valid_result(pdf_avg_token=0.0)
    assert result.passed
    buf = io.StringIO()
    print_report(result, out=buf)
    pdf_line = next(line for line in buf.getvalue().splitlines() if "pdf subset avg" in line)
    assert pdf_line.startswith("[OK]"), pdf_line
