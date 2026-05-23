"""논문.txt → curated_provenance.json + curated_issues.json 파서.

Spec §4.1 참조. 로컬에서 실행. 네트워크 호출 없음.

사용법:
    python -m mlops.scripts.parse_curated_papers \\
        --input /path/to/논문.txt \\
        --provenance mlops/data/curated_provenance.json \\
        --issues mlops/data/curated_issues.json
"""

import argparse
import json
import logging
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.curated import normalize_doi

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

PMID_RE = re.compile(r"PMID:?\s*(\d{5,9})", re.IGNORECASE)
PMCID_RE = re.compile(r"PMCID:?\s*(PMC\d+)", re.IGNORECASE)
DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s,;]+)", re.IGNORECASE)
TYPO_DOI_RE = re.compile(r"(?<![\d\.])0\.(\d{4,9}/[^\s,;]+)")
Q_HEADER_RE = re.compile(r"^Q(\d{3})\b")

PLACEHOLDER_TOKENS = ("XXXX",)
FUTURE_DOI_PREFIXES = (
    "10.1007/s40279-026",
    "10.1038/s41430-026",
    "10.1038/s41598-026",
    "10.1186/s40798-026",
)

# Q-id → LABELING_PLAN.md 카테고리 매핑 (Q001~Q121 범위)
# 미정의 Q는 'unknown' → ingest 단계에서 경고만, 적재 진행은 함
DEFAULT_CATEGORY = "unknown"


def extract_ids_from_lines(lines: list[str]) -> tuple[list[str], list[str], list[str]]:
    """라인 리스트에서 unique PMID, PMCID, DOI 추출 (등장 순서 유지, dedup)."""
    pmids: list[str] = []
    pmcids: list[str] = []
    dois: list[str] = []
    seen_p, seen_c, seen_d = set(), set(), set()
    for line in lines:
        for m in PMID_RE.finditer(line):
            val = m.group(1)
            if val not in seen_p:
                pmids.append(val)
                seen_p.add(val)
        for m in PMCID_RE.finditer(line):
            val = m.group(1).upper()
            if val not in seen_c:
                pmcids.append(val)
                seen_c.add(val)
        for m in DOI_RE.finditer(line):
            val = normalize_doi(m.group(1))
            if val and val not in seen_d:
                dois.append(val)
                seen_d.add(val)
    return pmids, pmcids, dois


def parse_papers_txt(path: Path) -> tuple[dict[str, list[str]], set[str]]:
    """논문.txt → {qid: [lines]} 매핑 + 삭제된 qid set.

    Q 헤더는 ``Q\\d{3}`` 시작 라인. '삭제' 마크 포함 시 deleted_qids에 추가.
    """
    qid_lines: dict[str, list[str]] = {}
    deleted: set[str] = set()
    current_qid: str | None = None

    # encoding="utf-8-sig": Windows에서 저장된 UTF-8 with BOM 파일 자동 처리
    with open(path, encoding="utf-8-sig") as f:
        for raw in f:
            line = raw.rstrip()
            m = Q_HEADER_RE.match(line)
            if m:
                current_qid = f"Q{m.group(1)}"
                qid_lines[current_qid] = [line]
                if "삭제" in line:
                    deleted.add(current_qid)
            elif current_qid:
                qid_lines[current_qid].append(line)
                if "질문 삭제" in line.strip():
                    deleted.add(current_qid)
    return qid_lines, deleted


def detect_issues(dois: list[str], raw_lines: list[str], qid: str) -> dict:
    """DOI / raw 라인에서 placeholder, 미래 prefix, typo, 중복 검출.

    반환: {
        "placeholder_doi": [...],
        "future_prefix_doi": [...],
        "typo_doi_autofixed": [...],
        "duplicate_in_query": [{"qid": str, "doi": str, "count": int}, ...],
    }
    각 entry는 {"qid": str, "value": str} 또는 typo의 경우
    {"qid": str, "original": str, "fixed": str}.
    """
    issues: dict = {
        "placeholder_doi": [],
        "future_prefix_doi": [],
        "typo_doi_autofixed": [],
        "duplicate_in_query": [],
    }

    for doi in dois:
        # placeholder: case-insensitive check (doi may already be lowercased via normalize_doi)
        if any(tok.lower() in doi.lower() for tok in PLACEHOLDER_TOKENS):
            issues["placeholder_doi"].append({"qid": qid, "value": doi})
        if any(doi.startswith(p) for p in FUTURE_DOI_PREFIXES):
            issues["future_prefix_doi"].append({"qid": qid, "value": doi})

    # duplicate_in_query: 동일 normalized DOI가 한 Q 내 2회 이상 등장
    # dois 파라미터는 extract_ids_from_lines이 이미 dedup한 값이므로,
    # 여기서는 raw_lines를 재스캔해 실제 등장 횟수를 셈
    doi_counts: dict[str, int] = {}
    for line in raw_lines:
        for m in DOI_RE.finditer(line):
            nd = normalize_doi(m.group(1))
            if nd:
                doi_counts[nd] = doi_counts.get(nd, 0) + 1
    for doi, count in doi_counts.items():
        if count >= 2:
            issues["duplicate_in_query"].append({"qid": qid, "doi": doi, "count": count})

    # typo: 라인 내 0.{prefix}/ 패턴 → 10.{prefix}/로 보정
    for line in raw_lines:
        for m in TYPO_DOI_RE.finditer(line):
            original = "0." + m.group(1)
            fixed = "10." + m.group(1)
            issues["typo_doi_autofixed"].append({"qid": qid, "original": original, "fixed": fixed})

    return issues


def build_provenance(
    qid_lines: dict[str, list[str]],
    deleted: set[str],
    issues_acc: dict,
) -> dict:
    """qid_lines + issues → provenance 구조 생성.

    - 삭제 Q는 스킵
    - 각 Q의 paper entry는 raw_id / resolved_* / indexed=None / failure_reason=None 형태로 초기화
    - 동일 paper(PMID 또는 normalized DOI 기준)는 multi-Q에 등재되어도 raw_id만 다르게 보존
    """
    provenance: dict = {}
    for qid, lines in qid_lines.items():
        if qid in deleted:
            continue
        pmids, pmcids, dois = extract_ids_from_lines(lines)

        # issue 검출 + acc 누적
        local_issues = detect_issues(dois, lines, qid)
        for k, v in local_issues.items():
            issues_acc.setdefault(k, []).extend(v)

        # placeholder/future는 paper에서 제거
        # typo DOI는 extract_ids_from_lines에서 매치 안 됨 → 별도로 typo_fixed_set에서 추가
        placeholder_set = {e["value"] for e in local_issues["placeholder_doi"]}
        future_set = {e["value"] for e in local_issues["future_prefix_doi"]}

        dois_clean = [normalize_doi(d) for d in dois if d not in placeholder_set and d not in future_set]
        dois_clean = [d for d in dois_clean if d]  # normalize 실패 제거

        # typo autofixed DOI를 dois_clean에 추가 (DOI_RE 미매치라 extract_ids_from_lines에서 누락됨)
        typo_fixed_set: set[str] = set()
        for e in local_issues["typo_doi_autofixed"]:
            nd = normalize_doi(e["fixed"])
            if nd:
                typo_fixed_set.add(nd)
        for nd in typo_fixed_set:
            if nd not in dois_clean:
                dois_clean.append(nd)

        papers = []
        # PMID-bearing entries
        for pmid in pmids:
            papers.append(
                {
                    "raw_id": f"PMID:{pmid}",
                    "raw_pmid": pmid,
                    "raw_doi": None,
                    "resolved_pmid": None,
                    "resolved_doi": None,
                    "resolved_title": None,
                    "indexed": None,
                    "already_in_corpus": None,
                    "fulltext_ok": None,
                    "failure_reason": None,
                    "is_typo_autofixed": False,
                    "search_categories": [DEFAULT_CATEGORY],
                }
            )
        # DOI entries — all DOIs as separate paper entries; dedup with downstream ingest
        for doi in dois_clean:
            is_typo = doi in typo_fixed_set
            papers.append(
                {
                    "raw_id": f"DOI:{doi}",
                    "raw_pmid": None,
                    "raw_doi": doi,
                    "resolved_pmid": None,
                    "resolved_doi": None,
                    "resolved_title": None,
                    "indexed": None,
                    "already_in_corpus": None,
                    "fulltext_ok": None,
                    "failure_reason": None,
                    "is_typo_autofixed": is_typo,
                    "search_categories": [DEFAULT_CATEGORY],
                }
            )

        provenance[qid] = {
            "category": DEFAULT_CATEGORY,
            "papers": papers,
        }

    # deleted queries를 issues에 별도 기록
    issues_acc.setdefault("deleted_queries", []).extend(sorted(deleted))
    return provenance


def _atomic_write_json(path: Path, data: object) -> None:
    """tmp + os.replace 패턴. 예외 발생 시 .tmp 파일 정리."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


def run(input_path: Path, provenance_path: Path, issues_path: Path) -> None:
    if not input_path.exists():
        logger.error("Input file not found: %s", input_path)
        sys.exit(1)
    qid_lines, deleted = parse_papers_txt(input_path)
    issues: dict = {
        "placeholder_doi": [],
        "future_prefix_doi": [],
        "typo_doi_autofixed": [],
        "duplicate_in_query": [],
        "deleted_queries": [],
    }
    provenance = build_provenance(qid_lines, deleted, issues)
    _atomic_write_json(provenance_path, provenance)
    _atomic_write_json(issues_path, issues)
    logger.info(
        "parsed: %d Qs (skipped %d deleted), placeholder=%d future=%d typo=%d duplicate=%d",
        len(provenance),
        len(deleted),
        len(issues["placeholder_doi"]),
        len(issues["future_prefix_doi"]),
        len(issues["typo_doi_autofixed"]),
        len(issues["duplicate_in_query"]),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="논문.txt → curated provenance + issues 파서")
    parser.add_argument("--input", required=True, type=Path, help="논문.txt 경로")
    parser.add_argument("--provenance", required=True, type=Path, help="curated_provenance.json 출력 경로")
    parser.add_argument("--issues", required=True, type=Path, help="curated_issues.json 출력 경로")
    args = parser.parse_args()
    run(args.input, args.provenance, args.issues)


if __name__ == "__main__":
    main()
