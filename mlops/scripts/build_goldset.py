"""curated_provenance.json + goldset_seed.jsonl → goldset.jsonl + summary 리포트.

Spec §4.3 참조. 로컬 실행, 네트워크 없음.

사용법:
    python -m mlops.scripts.build_goldset \\
        --seed mlops/eval/goldset_seed.jsonl \\
        --provenance mlops/data/curated_provenance.json \\
        --goldset mlops/eval/goldset.jsonl \\
        --summary mlops/eval/reports/goldset_summary.md
"""

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def classify_paper(paper: dict) -> str:
    """spec §4.3 책임 #2 분류.

    Returns: 'matchable' | 'failed' | 'no_pmid'
    - matchable: indexed=True AND resolved_pmid != ""
    - failed:    resolved_pmid != "" AND indexed=False
    - no_pmid:   resolved_pmid == "" (indexed 값과 무관)
    """
    pmid = paper.get("resolved_pmid") or ""
    if not pmid:
        return "no_pmid"  # pmid 비어있으면 indexed 값과 무관하게 no_pmid
    if paper.get("indexed"):
        return "matchable"
    return "failed"


def build_goldset_entry(seed: dict, q_prov: dict) -> dict | None:
    """spec §4.3 책임 #2, #3.

    Returns None when matchable set is empty (Method B: empty Q는 goldset 제외).
    """
    expected_pmids: list[str] = []
    curated_pmids_all: list[str] = []
    papers_failed: list[dict] = []

    for paper in q_prov["papers"]:
        klass = classify_paper(paper)
        pmid = paper.get("resolved_pmid") or ""
        if klass == "matchable":
            expected_pmids.append(pmid)
            curated_pmids_all.append(pmid)
        elif klass == "failed":
            curated_pmids_all.append(pmid)
            papers_failed.append(
                {
                    "raw_id": paper.get("raw_id", ""),
                    "resolved_pmid": pmid,
                    "failure_reason": paper.get("failure_reason") or "unknown",
                }
            )
        else:  # no_pmid
            papers_failed.append(
                {
                    "raw_id": paper.get("raw_id", ""),
                    "resolved_pmid": "",
                    "failure_reason": paper.get("failure_reason") or "unknown",
                }
            )

    if not expected_pmids:
        return None  # Method B 일관 적용

    total_curated = len(curated_pmids_all)
    coverage = len(expected_pmids) / total_curated if total_curated else 0.0

    return {
        **seed,
        "expected_pmids": expected_pmids,
        "curated_pmids_all": curated_pmids_all,
        "papers_failed": papers_failed,
        "corpus_coverage": round(coverage, 4),
    }


def run(seed_path: Path, provenance_path: Path, goldset_path: Path, summary_path: Path) -> None:
    seeds: list[dict] = []
    with open(seed_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                seeds.append(json.loads(line))

    provenance: dict = json.loads(provenance_path.read_text(encoding="utf-8"))

    eligible_entries: list[dict] = []
    corpus_gap: list[str] = []
    unlabeled: list[str] = []
    total_expected = 0
    total_curated = 0

    for seed in seeds:
        qid = seed["id"]
        if qid not in provenance:
            unlabeled.append(qid)
            continue
        entry = build_goldset_entry(seed, provenance[qid])
        # seed-wide totals (분모는 seed 전체 기준 — §8.5)
        q_prov = provenance[qid]
        for p in q_prov["papers"]:
            klass = classify_paper(p)
            if klass == "matchable":
                total_expected += 1
                total_curated += 1
            elif klass == "failed":
                total_curated += 1

        if entry is None:
            # matchable 없음 → goldset에서 제외
            curated_any = any(classify_paper(p) != "no_pmid" for p in q_prov["papers"])
            if curated_any:
                corpus_gap.append(qid)
            else:
                unlabeled.append(qid)
            continue
        eligible_entries.append(entry)

    # goldset.jsonl write
    goldset_path.parent.mkdir(parents=True, exist_ok=True)
    with open(goldset_path, "w", encoding="utf-8") as f:
        for entry in eligible_entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    # summary report
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    total_coverage = total_expected / total_curated if total_curated else 0.0
    lines = [
        "# Curated Goldset Summary",
        f"- seed total: {len(seeds)} queries",
        f"- metrics_eligible_queries: {len(eligible_entries)}",
        f"- corpus_gap_queries: {len(corpus_gap)}",
        f"- unlabeled_queries: {len(unlabeled)}",
        f"- total matchable PMIDs: {total_expected}",
        f"- total curated PMIDs (with resolved_pmid): {total_curated}",
        f"- **total corpus coverage: {total_coverage:.2%}**",
        "",
        "## corpus_gap_queries (큐레이션은 됐지만 corpus 매칭 가능 paper 없음)",
        *([f"- {q}" for q in corpus_gap] or ["(none)"]),
        "",
        "## unlabeled_queries (논문.txt 추가 큐레이션 필요)",
        *([f"- {q}" for q in unlabeled] or ["(none)"]),
    ]
    summary_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info(
        "goldset.jsonl: %d entries written (corpus_gap=%d, unlabeled=%d)",
        len(eligible_entries),
        len(corpus_gap),
        len(unlabeled),
    )


def main():
    parser = argparse.ArgumentParser(description="curated provenance + seed → goldset.jsonl")
    parser.add_argument("--seed", required=True, type=Path)
    parser.add_argument("--provenance", required=True, type=Path)
    parser.add_argument("--goldset", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    args = parser.parse_args()
    run(args.seed, args.provenance, args.goldset, args.summary)


if __name__ == "__main__":
    main()
