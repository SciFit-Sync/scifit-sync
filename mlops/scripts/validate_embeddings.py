"""Pre-Upsert Validation 게이트 — design §3.3.1.

jsonl 산출물의 통계를 산출하고 임계 미달 시 fail-fast abort.
ChromaDB upsert 진입 직전 자동 호출 또는 단독 CLI로 실행.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from statistics import mean, quantiles

from mlops.eval.validation_thresholds import (
    AVG_TOKEN_MAX,
    AVG_TOKEN_MIN,
    CHUNKS_PER_PAPER_MAX,
    CHUNKS_PER_PAPER_MIN,
    EMBEDDING_DIM,
    EVIDENCE_WEIGHT_DISTINCT_MIN,
    EVIDENCE_WEIGHT_HIGH_CUTOFF,
    EVIDENCE_WEIGHT_HIGH_SHARE_MIN,
    EVIDENCE_WEIGHT_MAX_BUCKET_MAX,
    IDENTIFIER_FILL_RATE_MIN,
    PAPER_DOI_FILL_RATE_INFO_MIN,
    PDF_AVG_TOKEN_MAX,
    PDF_AVG_TOKEN_MIN,
    PUBLICATION_TYPES_FILL_RATE_MIN,
    REQUIRED_KEYS,
    TOKEN_OVER_512_RATIO_MAX,
    TOKEN_P99_MAX,
)

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    schema_ok: bool = False
    missing_keys: set[str] = field(default_factory=set)
    identifier_fill_rate: float = 0.0
    paper_doi_fill_rate: float = 0.0
    publication_types_fill_rate: float = 0.0
    evidence_weight_distinct: int = 0
    evidence_weight_05_ratio: float = 0.0
    evidence_weight_max_bucket_share: float = 0.0
    evidence_weight_high_share: float = 0.0
    avg_token: float = 0.0
    p99_token: float = 0.0
    over_512_ratio: float = 0.0
    chunks_per_paper_avg: float = 0.0
    pdf_avg_token: float = 0.0
    embedding_dim: int = 0
    total_chunks: int = 0

    @property
    def passed(self) -> bool:
        return (
            self.schema_ok
            and self.identifier_fill_rate >= IDENTIFIER_FILL_RATE_MIN
            and self.publication_types_fill_rate >= PUBLICATION_TYPES_FILL_RATE_MIN
            and self.evidence_weight_distinct >= EVIDENCE_WEIGHT_DISTINCT_MIN
            and self.evidence_weight_max_bucket_share <= EVIDENCE_WEIGHT_MAX_BUCKET_MAX
            and self.evidence_weight_high_share >= EVIDENCE_WEIGHT_HIGH_SHARE_MIN
            and AVG_TOKEN_MIN <= self.avg_token <= AVG_TOKEN_MAX
            and self.p99_token <= TOKEN_P99_MAX
            and self.over_512_ratio <= TOKEN_OVER_512_RATIO_MAX
            and CHUNKS_PER_PAPER_MIN <= self.chunks_per_paper_avg <= CHUNKS_PER_PAPER_MAX
            and self.embedding_dim == EMBEDDING_DIM
            # pdf subset 회귀 검증 — pdf_avg_token==0 이면 local_pdf 청크 없는 케이스(skip)
            and (self.pdf_avg_token == 0 or PDF_AVG_TOKEN_MIN <= self.pdf_avg_token <= PDF_AVG_TOKEN_MAX)
        )


def _iter_records(paths: list[Path]):
    for path in paths:
        opener = gzip.open if path.suffix == ".gz" else open
        with opener(path, "rt", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    yield json.loads(line)


def validate_jsonl(paths: list[Path]) -> ValidationResult:
    result = ValidationResult()
    tokens: list[int] = []
    ew_values: list[float] = []
    paper_chunks: Counter[str] = Counter()
    pdf_tokens: list[int] = []
    schema_ok = True
    missing_keys: set[str] = set()
    id_filled = 0
    doi_filled = 0
    pub_filled = 0
    emb_dims: set[int] = set()
    total = 0

    for rec in _iter_records(paths):
        total += 1
        for k in REQUIRED_KEYS:
            if k not in rec:
                missing_keys.add(k)
                schema_ok = False
        if rec.get("paper_doi") or rec.get("paper_pmid"):
            id_filled += 1
        if rec.get("paper_doi"):
            doi_filled += 1
        if rec.get("publication_types"):
            pub_filled += 1
        tc = int(rec.get("token_count", 0))
        if tc:
            tokens.append(tc)
            if rec.get("fulltext_source") == "local_pdf":
                pdf_tokens.append(tc)
        ew = float(rec.get("evidence_weight", 0.5))
        ew_values.append(ew)
        key = rec.get("paper_doi") or rec.get("paper_pmid") or "_unknown"
        paper_chunks[key] += 1
        emb = rec.get("embedding")
        if isinstance(emb, list):
            emb_dims.add(len(emb))

    result.total_chunks = total
    result.schema_ok = schema_ok
    result.missing_keys = missing_keys
    if total:
        result.identifier_fill_rate = id_filled / total
        result.paper_doi_fill_rate = doi_filled / total
        result.publication_types_fill_rate = pub_filled / total
    if tokens:
        result.avg_token = mean(tokens)
        if len(tokens) >= 100:
            result.p99_token = quantiles(tokens, n=100)[98]
        else:
            result.p99_token = max(tokens)
        result.over_512_ratio = sum(1 for t in tokens if t > 512) / len(tokens)
    if pdf_tokens:
        result.pdf_avg_token = mean(pdf_tokens)
    if ew_values:
        ew_buckets = Counter(round(v, 2) for v in ew_values)
        result.evidence_weight_distinct = len(ew_buckets)
        result.evidence_weight_05_ratio = sum(1 for v in ew_values if abs(v - 0.5) < 1e-6) / len(ew_values)
        # 붕괴 탐지(값 불문): 최대 단일 버킷 점유율 + 고근거(>=cutoff) 청크 질량
        result.evidence_weight_max_bucket_share = max(ew_buckets.values()) / len(ew_values)
        result.evidence_weight_high_share = sum(1 for v in ew_values if v >= EVIDENCE_WEIGHT_HIGH_CUTOFF) / len(
            ew_values
        )
    if paper_chunks:
        result.chunks_per_paper_avg = mean(paper_chunks.values())
    if emb_dims:
        result.embedding_dim = next(iter(emb_dims)) if len(emb_dims) == 1 else -1
    return result


def print_report(result: ValidationResult, out=sys.stderr) -> None:
    def mark(ok: bool) -> str:
        return "OK" if ok else "FAIL"

    rows = [
        (
            "schema",
            result.schema_ok,
            f"{len(REQUIRED_KEYS) - len(result.missing_keys)}/{len(REQUIRED_KEYS)} keys, missing={sorted(result.missing_keys)}",
        ),
        (
            "identifier coverage",
            result.identifier_fill_rate >= IDENTIFIER_FILL_RATE_MIN,
            f"{result.identifier_fill_rate:.4f}",
        ),
        (
            "paper_doi fill rate",
            result.paper_doi_fill_rate >= PAPER_DOI_FILL_RATE_INFO_MIN,
            f"{result.paper_doi_fill_rate:.4f} (info-only)",
        ),
        (
            "publication_types",
            result.publication_types_fill_rate >= PUBLICATION_TYPES_FILL_RATE_MIN,
            f"{result.publication_types_fill_rate:.4f}",
        ),
        (
            "evidence_weight",
            # 라벨은 passed 집계와 동일한 3신호 AND: distinct + 최대버킷점유 + 고근거질량.
            result.evidence_weight_distinct >= EVIDENCE_WEIGHT_DISTINCT_MIN
            and result.evidence_weight_max_bucket_share <= EVIDENCE_WEIGHT_MAX_BUCKET_MAX
            and result.evidence_weight_high_share >= EVIDENCE_WEIGHT_HIGH_SHARE_MIN,
            f"distinct={result.evidence_weight_distinct}, "
            f"max_bucket={result.evidence_weight_max_bucket_share:.2f}, "
            f"high(>={EVIDENCE_WEIGHT_HIGH_CUTOFF})={result.evidence_weight_high_share:.2f}, "
            f"0.5_ratio={result.evidence_weight_05_ratio:.2f}(info)",
        ),
        (
            "avg token",
            AVG_TOKEN_MIN <= result.avg_token <= AVG_TOKEN_MAX,
            f"{result.avg_token:.1f} (range {AVG_TOKEN_MIN}~{AVG_TOKEN_MAX})",
        ),
        ("p99 token", result.p99_token <= TOKEN_P99_MAX, f"{result.p99_token:.0f} (<=  {TOKEN_P99_MAX})"),
        ("> 512 ratio", result.over_512_ratio <= TOKEN_OVER_512_RATIO_MAX, f"{result.over_512_ratio:.3f}"),
        (
            "chunks/paper",
            CHUNKS_PER_PAPER_MIN <= result.chunks_per_paper_avg <= CHUNKS_PER_PAPER_MAX,
            f"avg {result.chunks_per_paper_avg:.1f}",
        ),
        (
            "pdf subset avg",
            # 라벨도 passed 집계(71행)와 동일하게 pdf_avg_token==0(local_pdf 청크 없음
            # =--skip-local-pdf 정상 케이스) 예외를 둔다. 이전엔 이 예외가 없어
            # 정상 skip인데도 라벨만 [FAIL]로 찍혀 passed와 어긋났다.
            result.pdf_avg_token == 0 or PDF_AVG_TOKEN_MIN <= result.pdf_avg_token <= PDF_AVG_TOKEN_MAX,
            f"{result.pdf_avg_token:.1f}",
        ),
        ("embedding dim", result.embedding_dim == EMBEDDING_DIM, f"{result.embedding_dim}"),
    ]
    print("=== validate_embeddings ===", file=out)
    for name, ok, detail in rows:
        print(f"[{mark(ok)}] {name}: {detail}", file=out)
    print(f"\nVERDICT: {'PASS' if result.passed else 'FAIL'} (total {result.total_chunks} chunks)", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Pre-Upsert Validation")
    parser.add_argument("--input", type=Path, nargs="+", required=True, help="jsonl(.gz) paths")
    parser.add_argument("--fail-fast", action="store_true", help="실패 시 exit 2")
    args = parser.parse_args(argv)

    result = validate_jsonl(args.input)
    print_report(result)
    if not result.passed and args.fail_fast:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
