"""임베딩 jsonl.gz의 publication_types / evidence_weight 사후 보강.

기존 임베딩 파일(`local_pdf_ingest.jsonl.gz` 등)이 publication_types=[] /
evidence_weight=0.5 fallback 으로만 생성된 경우, paper_pmid 기준으로 NCBI efetch
를 호출해 두 필드만 in-place 갱신한다. embedding 벡터는 재계산하지 않는다.

사용법:
    python -m mlops.scripts.patch_emb_publication_types \\
        --jsonl mlops/data/emb_bge-large/local_pdf_ingest.jsonl.gz \\
        --output mlops/data/emb_bge-large/local_pdf_ingest.patched.jsonl.gz \\
        [--manifest mlops/data/local_pdfs/manifest.json] \\
        [--batch-size 100]

manifest 인자를 주면 manifest.json의 papers[*].publication_types / pmid도 함께 갱신
(원본은 `.bak` 보존).

PMID가 없는 paper(preprint 등)는 그대로 두며 evidence_weight=0.5 fallback 유지.
"""

from __future__ import annotations

import argparse
import gzip
import json
import logging
import shutil
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.evidence import calculate_evidence_weight  # noqa: E402
from mlops.scripts.ingest_curated_pmids import efetch_pubmed_batch  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)


def _chunked(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def collect_doi_pmid(jsonl_path: Path) -> dict[str, str]:
    """jsonl.gz 1-pass → {doi: pmid} (paper 단위, doi가 키)."""
    papers: dict[str, str] = {}
    with gzip.open(jsonl_path, "rt", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            doi = (r.get("paper_doi") or "").strip()
            pmid = (r.get("paper_pmid") or "").strip()
            if doi and doi not in papers:
                papers[doi] = pmid
    return papers


def fetch_publication_types(pmids: list[str], batch_size: int) -> dict[str, list[str]]:
    """PMID들을 batch_size 단위로 efetch → {pmid: publication_types}."""
    result: dict[str, list[str]] = {}
    total = len(pmids)
    for i, batch in enumerate(_chunked(pmids, batch_size), 1):
        logger.info("efetch batch %d (%d pmids, accumulated=%d/%d)", i, len(batch), len(result), total)
        data = efetch_pubmed_batch(batch)
        for pmid, meta in data.items():
            result[pmid] = list(meta.get("publication_types") or [])
    return result


def build_doi_index(
    doi_to_pmid: dict[str, str],
    pmid_to_types: dict[str, list[str]],
) -> dict[str, tuple[list[str], float]]:
    """{doi: (publication_types, evidence_weight)}."""
    out: dict[str, tuple[list[str], float]] = {}
    for doi, pmid in doi_to_pmid.items():
        types = pmid_to_types.get(pmid, []) if pmid else []
        weight = calculate_evidence_weight(types)
        out[doi] = (types, weight)
    return out


def patch_jsonl(
    src: Path,
    dst: Path,
    doi_index: dict[str, tuple[list[str], float]],
) -> tuple[int, Counter, Counter]:
    """jsonl.gz를 1-pass로 다시 읽어 두 필드만 갱신해 새 파일에 기록.

    반환: (총 chunks, evidence_weight 분포, publication_types non-empty/empty 카운터)
    """
    total = 0
    ew_dist: Counter = Counter()
    pt_dist: Counter = Counter()
    with gzip.open(src, "rt", encoding="utf-8") as fin, gzip.open(dst, "wt", encoding="utf-8") as fout:
        for line in fin:
            r = json.loads(line)
            doi = (r.get("paper_doi") or "").strip()
            if doi in doi_index:
                types, weight = doi_index[doi]
                r["publication_types"] = types
                r["evidence_weight"] = weight
            ew_dist[round(float(r.get("evidence_weight", 0.5)), 2)] += 1
            pt_dist["non-empty" if r.get("publication_types") else "empty"] += 1
            fout.write(json.dumps(r, ensure_ascii=False) + "\n")
            total += 1
    return total, ew_dist, pt_dist


def patch_manifest(
    manifest_path: Path,
    doi_to_pmid: dict[str, str],
    pmid_to_types: dict[str, list[str]],
) -> int:
    """manifest.json papers[*]에 pmid + publication_types를 in-place 갱신.

    원본은 `manifest.json.bak`으로 보존. doi가 manifest와 매칭되지 않으면 skip.
    """
    backup = manifest_path.with_suffix(manifest_path.suffix + ".bak")
    if not backup.exists():
        shutil.copy2(manifest_path, backup)
        logger.info("manifest 백업 생성: %s", backup)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    updated = 0
    for paper in data.get("papers", []):
        doi = (paper.get("doi") or "").strip().lower()
        if not doi or doi not in doi_to_pmid:
            continue
        pmid = doi_to_pmid[doi]
        types = pmid_to_types.get(pmid, []) if pmid else []
        if pmid and not paper.get("pmid"):
            paper["pmid"] = pmid
        if types:
            paper["publication_types"] = types
            updated += 1
    manifest_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updated


def run(jsonl: Path, output: Path, manifest: Path | None, batch_size: int) -> int:
    if not jsonl.exists():
        logger.error("입력 jsonl 없음: %s", jsonl)
        return 1
    if output.exists():
        logger.error("출력 파일이 이미 존재 — 덮어쓰기 방지: %s", output)
        return 1

    doi_to_pmid = collect_doi_pmid(jsonl)
    logger.info("unique papers: %d (with PMID: %d)", len(doi_to_pmid), sum(1 for v in doi_to_pmid.values() if v))

    pmids = sorted({v for v in doi_to_pmid.values() if v})
    if not pmids:
        logger.warning("PMID 0건 — efetch 호출 생략. 결과는 입력과 동일")
        pmid_to_types: dict[str, list[str]] = {}
    else:
        pmid_to_types = fetch_publication_types(pmids, batch_size=batch_size)
        logger.info("efetch 결과: %d/%d PMIDs에서 publication_types 회수", len(pmid_to_types), len(pmids))

    doi_index = build_doi_index(doi_to_pmid, pmid_to_types)
    paper_with_types = sum(1 for _, (t, _) in doi_index.items() if t)
    logger.info("paper 단위 publication_types 채워짐: %d/%d", paper_with_types, len(doi_index))

    total, ew_dist, pt_dist = patch_jsonl(jsonl, output, doi_index)
    logger.info("patched jsonl 기록: %s (%d chunks)", output, total)
    logger.info("=== evidence_weight 분포 ===")
    for k, v in sorted(ew_dist.items()):
        logger.info("  %s : %d chunks (%.1f%%)", k, v, v / total * 100)
    logger.info("=== publication_types ===")
    for k, v in pt_dist.items():
        logger.info("  %s : %d chunks (%.1f%%)", k, v, v / total * 100)

    if manifest:
        if not manifest.exists():
            logger.warning("manifest 경로 없음 — 스킵: %s", manifest)
        else:
            n = patch_manifest(manifest, doi_to_pmid, pmid_to_types)
            logger.info("manifest %d개 entry 갱신: %s", n, manifest)

    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="임베딩 jsonl.gz의 publication_types/evidence_weight 사후 보강")
    p.add_argument("--jsonl", type=Path, required=True, help="입력 jsonl.gz 경로")
    p.add_argument("--output", type=Path, required=True, help="출력 jsonl.gz 경로 (덮어쓰기 금지)")
    p.add_argument("--manifest", type=Path, default=None, help="(선택) manifest.json 동시 갱신")
    p.add_argument("--batch-size", type=int, default=100, help="efetch batch 크기 (default 100)")
    args = p.parse_args()
    return run(args.jsonl, args.output, args.manifest, args.batch_size)


if __name__ == "__main__":
    raise SystemExit(main())
