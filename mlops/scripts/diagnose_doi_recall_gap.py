"""DOI 매칭 갭 진단 스크립트 (sanity check).

가설: `run_eval.py`가 PMID로만 매칭하는데 (D-M11 이전 코드), corpus의 일부
paper는 PMID 없이 DOI만 있어서 (D-M11: DOI primary, PMID nullable 보조)
false negative가 발생할 수 있다.

본 스크립트는 다음을 측정한다:
1. 현재 PMID-only 매칭으로 candidates.jsonl 기준 hit 수
2. PMID OR DOI 매칭으로 candidates.jsonl 기준 hit 수
3. (2) - (1) = DOI 매칭 보강 시 회복 가능 폭 (카테고리별)

PMID → DOI 변환은 OpenAlex API 사용 (무료, 결정론적, 50개씩 batch).
LLM 호출 없음.

사용법 (GPU 서버 기준):
    python -m mlops.scripts.diagnose_doi_recall_gap \
        --goldset mlops/eval/goldset.jsonl \
        --candidates mlops/eval/candidates.jsonl \
        --mailto your@email \
        --output mlops/eval/reports/doi_gap_diagnosis.md

한계: candidates.jsonl이 paper top-K(현재 5)만 들고 있어서 실제 평가의
top-10 retrieval과 다를 수 있다. 본 결과는 "방향성" 검증이며, 본격 수치는
run_eval.py 매칭 로직을 union으로 바꾼 뒤 재실행해서 확인해야 한다.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

OPENALEX_BASE = "https://api.openalex.org/works"
BATCH = 50


def load_jsonl(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def fetch_pmid_to_doi(pmids: list[str], mailto: str | None = None) -> dict[str, str]:
    """OpenAlex bulk lookup: PMID → DOI (lowercase, URL prefix 제거)."""
    mapping: dict[str, str] = {}
    pmids = sorted({p for p in pmids if p})
    logger.info("OpenAlex PMID→DOI lookup: %d unique PMIDs", len(pmids))
    for i in range(0, len(pmids), BATCH):
        chunk = pmids[i : i + BATCH]
        # OpenAlex same-key OR: 키 한 번, 값들만 `|`로 묶기. `pmid:X|pmid:Y`로 보내면 400 Bad Request.
        params = {
            "filter": f"pmid:{'|'.join(chunk)}",
            "per-page": BATCH,
            "select": "ids",
        }
        if mailto:
            params["mailto"] = mailto

        data = None
        for attempt in range(3):
            try:
                r = requests.get(OPENALEX_BASE, params=params, timeout=30)
                r.raise_for_status()
                data = r.json()
                break
            except requests.RequestException as e:
                logger.warning("retry %d/3: %s", attempt + 1, e)
                time.sleep(2**attempt)
        if data is None:
            logger.error("OpenAlex batch failed (skipped): first=%s", chunk[0])
            continue

        results = data.get("results") or []
        if not results and len(chunk) > 5:
            logger.warning(
                "suspicious empty results: batch=%d, first=%s — filter 문법 또는 응답 형식 변경 의심",
                len(chunk),
                chunk[0],
            )
        for w in results:
            ids = w.get("ids") or {}
            pmid_url = ids.get("pmid") or ""
            doi_url = ids.get("doi") or ""
            pmid = pmid_url.rsplit("/", 1)[-1] if pmid_url else ""
            doi = doi_url.replace("https://doi.org/", "").lower() if doi_url else ""
            if pmid and doi:
                mapping[pmid] = doi
        time.sleep(0.1)  # polite pool 매너
    logger.info("Mapped %d/%d PMIDs to DOI", len(mapping), len(pmids))
    return mapping


def main() -> int:
    parser = argparse.ArgumentParser(description="DOI 매칭 갭 진단")
    parser.add_argument("--goldset", type=Path, required=True)
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--mailto", type=str, default=None, help="OpenAlex polite pool email")
    parser.add_argument("--output", type=Path, default=None, help="Markdown 출력 (생략 시 stdout)")
    args = parser.parse_args()

    goldset = {item["id"]: item for item in load_jsonl(args.goldset)}
    candidates = {item["id"]: item for item in load_jsonl(args.candidates)}
    logger.info("goldset=%d qid, candidates=%d qid", len(goldset), len(candidates))
    common = set(goldset) & set(candidates)
    logger.info("intersection=%d qid", len(common))

    all_pmids: set[str] = set()
    for qid in common:
        all_pmids.update(str(p) for p in goldset[qid].get("expected_pmids", []))
        for c in candidates[qid].get("candidates", []):
            if c.get("pmid"):
                all_pmids.add(str(c["pmid"]))

    pmid_to_doi = fetch_pmid_to_doi(sorted(all_pmids), mailto=args.mailto)

    by_cat: dict[str, dict[str, int]] = defaultdict(
        lambda: {"n": 0, "expected": 0, "pmid_hits": 0, "doi_extra": 0, "expected_no_doi": 0}
    )
    overall = {"n": 0, "expected": 0, "pmid_hits": 0, "doi_extra": 0, "expected_no_doi": 0}

    for qid in sorted(common):
        item = goldset[qid]
        cat = item.get("category", "_unknown")
        expected_pmids = {str(p) for p in item.get("expected_pmids", [])}
        if not expected_pmids:
            continue
        expected_dois = {pmid_to_doi[p] for p in expected_pmids if p in pmid_to_doi}
        expected_no_doi = sum(1 for p in expected_pmids if p not in pmid_to_doi)

        retrieved_pmids = [str(c["pmid"]) for c in candidates[qid].get("candidates", []) if c.get("pmid")]
        pmid_match = expected_pmids & set(retrieved_pmids)
        # DOI 기준 추가 매칭: PMID로는 안 잡혔는데 DOI는 expected와 일치
        doi_match_pmids = {p for p in retrieved_pmids if pmid_to_doi.get(p) in expected_dois and p not in pmid_match}

        for bucket in (by_cat[cat], overall):
            bucket["n"] += 1
            bucket["expected"] += len(expected_pmids)
            bucket["pmid_hits"] += len(pmid_match)
            bucket["doi_extra"] += len(doi_match_pmids)
            bucket["expected_no_doi"] += expected_no_doi

    cand_k = max((len(candidates[q].get("candidates", [])) for q in common), default=0)
    delta_overall = 100 * overall["doi_extra"] / max(overall["expected"], 1)

    lines: list[str] = [
        "# DOI 매칭 갭 진단",
        "",
        f"- goldset: `{args.goldset}` ({len(goldset)} qid)",
        f"- candidates: `{args.candidates}` ({len(candidates)} qid, top-{cand_k}/query)",
        f"- 분석 대상 qid (expected_pmids 있음): {overall['n']}",
        f"- OpenAlex PMID→DOI: {len(pmid_to_doi)}/{len(all_pmids)} 매핑 성공",
        "",
        "## Overall",
        "",
        "| 항목 | 값 |",
        "| --- | --- |",
        f"| expected_pmids 총 수 | {overall['expected']} |",
        f"| PMID-only hits (현재 매칭) | {overall['pmid_hits']} |",
        f"| DOI extra hits (추가 매칭 가능) | **{overall['doi_extra']}** |",
        f"| expected 중 DOI 변환 실패 | {overall['expected_no_doi']} |",
        f"| Δ pp (회복 가능 폭) | **{delta_overall:.2f}** |",
        "",
        "## Per category",
        "",
        "| cat | n | exp | pmid_hit | doi_extra | Δ pp |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for cat in sorted(by_cat):
        s = by_cat[cat]
        delta = 100 * s["doi_extra"] / max(s["expected"], 1)
        lines.append(f"| {cat} | {s['n']} | {s['expected']} | {s['pmid_hits']} | **{s['doi_extra']}** | {delta:.2f} |")
    lines += [
        "",
        "## 해석",
        "",
        "- **doi_extra가 큰 카테고리**일수록 DOI 매칭 추가로 recall 회복 효과가 큼.",
        "- **expected 중 DOI 변환 실패**가 많으면 OpenAlex에 없는 PMID라 별도 조사 필요.",
        f"- 본 검증은 candidates.jsonl(top-{cand_k}) 한정 — 실제 평가는 top-10 retrieve라 효과 폭이 더 클 수 있음.",
        "- 가설 검증 후속: run_eval matching을 PMID∪DOI로 확장 → 동일 임베딩으로 재평가하여 실제 회복 폭 측정.",
    ]

    text = "\n".join(lines)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        logger.info("written: %s", args.output)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
