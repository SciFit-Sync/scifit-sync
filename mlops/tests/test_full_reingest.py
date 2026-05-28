"""full_reingest orchestrator 단위 테스트 (Stage 3.5 게이트만 우선)."""

import gzip
import json
import tempfile
from pathlib import Path

from mlops.scripts.full_reingest import stage3_5_validate


def _make_ok_jsonl(n=60) -> Path:
    """모든 임계 충족하는 jsonl."""
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
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    records = []
    for p in range(3):
        for c in range(25):
            i = p * 25 + c
            records.append(
                {
                    "chunk_index": c,
                    "paper_pmid": f"pmid{p}",
                    "paper_title": "T",
                    "section_name": "Methods",
                    # local_pdf 서브셋은 PDF_AVG_TOKEN 범위(150~250) 안으로,
                    # 그 외는 AVG_TOKEN 범위(300~450) 만족하도록 분기
                    "token_count": 200 if p == 0 else 400,
                    "search_categories": [],
                    "paper_doi": f"10.1/{p}",
                    "publication_types": types_list[i % len(types_list)],
                    "evidence_weight": weights[i % len(weights)],
                    "fulltext_source": "local_pdf" if p == 0 else "pmc",
                    "published_year": 2018,
                    "embedding": [0.1] * 1024,
                }
            )
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return tmp


def test_stage3_5_passes_on_good_jsonl():
    path = _make_ok_jsonl(60)
    assert stage3_5_validate(path) is True


def test_stage3_5_fails_on_bad_jsonl():
    path = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_index": 0}) + "\n")  # 키 통째 누락
    assert stage3_5_validate(path) is False
