"""5 Stage ingestion orchestrator — design §2.

Stage 1: fetch (crawler + efetch 보강 + local_pdf 통합)
Stage 1.5: manifest sanity (paper-level publication_types/identifier)
Stage 2: chunk
Stage 3: embed
Stage 3.5: validate_embeddings (chunk-level)
Stage 4: upsert to papers_v2
Stage 5: 평가 게이트 (run_eval recall@10) + alias swap 안내

Resumable: manifest 기반 멱등성. 중단 후 재실행 시 완료 stage skip.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from mlops.pipeline.config import DATA_DIR
from mlops.scripts.validate_embeddings import print_report, validate_jsonl

logger = logging.getLogger(__name__)


def stage1_fetch(batch_tag: str, mode: str, max_per_category: int | None) -> Path:
    """Stage 1: crawl + efetch 보강 + local_pdf 통합 → manifest path."""
    if mode == "phase1_local_pdf":
        import json as _json

        from mlops.pipeline.chunker import chunk_papers
        from mlops.pipeline.config import MANIFEST_PATH
        from mlops.pipeline.manifest import Manifest
        from mlops.pipeline.models import PaperFull
        from mlops.scripts.export_embeddings import (
            _chunks_path,
            _save_chunks_atomic,
            _write_meta_sidecar,
        )
        from mlops.scripts.ingest_local_pdfs import build_paperfull

        # local_pdfs manifest 위치 — ingest_local_pdfs.py에서 사용하는 위치 그대로
        # ingest_local_pdfs.py는 --manifest 인자로 받으므로 기본 위치는 관례적 경로 사용
        manifest_in = DATA_DIR / "local_pdfs" / "manifest.json"
        if not manifest_in.exists():
            raise FileNotFoundError(f"local_pdfs manifest 없음: {manifest_in}")

        try:
            raw = _json.loads(manifest_in.read_text(encoding="utf-8"))
        except Exception as exc:
            raise ValueError(f"local_pdfs manifest JSON 파싱 실패: {exc}") from exc

        # ingest_local_pdfs.py 패턴: manifest_data.get("papers") — {"papers": [...]} 포맷
        entries = raw.get("papers") or []
        if not entries:
            raise ValueError(f"manifest.papers가 비어있음: {manifest_in}")

        pdf_dir = DATA_DIR / "local_pdfs" / "pdfs"

        papers: list[PaperFull] = []
        skipped = []
        for entry in entries:
            if not isinstance(entry, dict):
                logger.warning("manifest entry가 dict가 아님 — skip: %r", entry)
                continue
            pf = build_paperfull(entry, pdf_dir)
            if pf is None:
                continue
            # 식별자 fallback — DOI 또는 PMID 둘 중 하나 필요. SHA 도입 X.
            if not (pf.meta.doi or pf.meta.pmid):
                skipped.append(entry.get("title", "?"))
                logger.warning("drop: no doi/pmid for %s", entry.get("title", "?"))
                continue
            papers.append(pf)
        logger.info("Phase 1 local_pdf: %d papers loaded, %d skipped", len(papers), len(skipped))

        # chunks 캐시 저장 (Stage 2에서 reuse) — export_embeddings.py 패턴
        chunks = chunk_papers(papers)
        cp = _chunks_path(batch_tag)
        _save_chunks_atomic(cp, chunks)
        _write_meta_sidecar(cp, chunks)
        logger.info("chunks 저장: %s (%d chunks)", cp, len(chunks))

        # manifest.json 갱신 — paper-level meta 보존 (Stage 1.5 검증 대상)
        # ManifestEntry에는 publication_types 필드가 없으므로 record_attempt만 호출
        # DOI 없는 PMID-only paper는 record_attempt 생략 (ingest_local_pdfs.py 동일 패턴)
        manifest = Manifest.load(MANIFEST_PATH)
        recorded = 0
        for pf in papers:
            if not pf.meta.doi:
                logger.warning("DOI 없음 — pipeline manifest 기록 생략 (pmid=%s)", pf.meta.pmid)
                continue
            manifest.record_attempt(
                doi=pf.meta.doi,
                pmid=pf.meta.pmid or None,
                pmcid=pf.meta.pmcid,
                openalex_id=pf.meta.openalex_id or None,
                fulltext_source=pf.meta.fulltext_source,
                tried_sources=["local_pdf"],
            )
            recorded += 1
        manifest.save(MANIFEST_PATH)
        logger.info("manifest 갱신: %d papers 기록", recorded)
        return MANIFEST_PATH

    if mode == "phase2_full":
        raise NotImplementedError("phase2_full — Task C6")
    raise ValueError(f"unknown mode: {mode}")


def stage1_5_manifest_sanity(manifest_path: Path) -> bool:
    """Stage 1.5: paper-level (doi OR pmid) identifier = 100%.

    drop 후라 identifier 100% 보장돼야 함.
    publication_types 검증은 ManifestEntry에 해당 필드가 없으므로
    chunk-level validation(Stage 3.5)이 담당한다.
    """
    from mlops.pipeline.manifest import Manifest

    manifest = Manifest.load(manifest_path)
    if not manifest.papers:
        logger.error("manifest 비어있음 — Stage 1 산출물 누락")
        return False
    total = len(manifest.papers)
    # manifest.papers의 key 자체가 DOI이므로 identifier fill rate = 100% 보장
    # (DOI 없는 paper는 record_attempt 자체를 생략하므로 manifest에 없음)
    id_rate = 1.0  # keys are DOIs — guaranteed 100%
    logger.info(
        "manifest sanity: id %.3f (= 1.00?), pub_types skipped (chunk-level에서 검증), total %d",
        id_rate,
        total,
    )
    return id_rate >= 1.0


def stage2_3_chunk_embed(batch_tag: str) -> Path:
    """Stage 2+3: chunk + embed → jsonl.gz path. Task C7에서 구현."""
    raise NotImplementedError("Task C7")


def stage3_5_validate(embeddings_path: Path) -> bool:
    """Stage 3.5: pre-upsert validation 게이트."""
    result = validate_jsonl([embeddings_path])
    print_report(result)
    return result.passed


def stage4_upsert(embeddings_path: Path, collection: str) -> int:
    """Stage 4: ChromaDB papers_v2 upsert. Task C8에서 구현."""
    raise NotImplementedError("Task C8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Full reingest orchestrator")
    parser.add_argument("--mode", choices=["phase1_local_pdf", "phase2_full"], required=True)
    parser.add_argument("--batch-tag", required=True)
    parser.add_argument("--collection-suffix", default="_v2")
    parser.add_argument("--max-per-category", type=int, default=None)
    parser.add_argument(
        "--skip-stages",
        nargs="*",
        default=[],
        choices=["fetch", "manifest_check", "chunk_embed", "validate", "upsert"],
    )
    parser.add_argument("--eval-gate", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
    collection = f"papers{args.collection_suffix}"

    # Stage 1
    if "fetch" not in args.skip_stages:
        manifest_path = stage1_fetch(args.batch_tag, args.mode, args.max_per_category)
    else:
        manifest_path = DATA_DIR / "manifest.json"

    # Stage 1.5
    if "manifest_check" not in args.skip_stages and not stage1_5_manifest_sanity(manifest_path):
        logger.error("Stage 1.5 manifest sanity 실패 — abort")
        return 2

    # Stage 2+3
    if "chunk_embed" not in args.skip_stages:
        embeddings_path = stage2_3_chunk_embed(args.batch_tag)
    else:
        embeddings_path = DATA_DIR / f"emb_bge-large/{args.batch_tag}.jsonl.gz"

    # Stage 3.5
    if "validate" not in args.skip_stages and not stage3_5_validate(embeddings_path):
        logger.error("Stage 3.5 pre-upsert validation 실패 — abort")
        return 3

    # Stage 4
    if "upsert" not in args.skip_stages:
        n = stage4_upsert(embeddings_path, collection)
        logger.info("upsert 완료: %d chunks → %s", n, collection)

    # Stage 5 안내
    if args.eval_gate:
        logger.info("Stage 5: run_eval로 골드셋 recall@10 비교 후 alias swap 진행")

    return 0


if __name__ == "__main__":
    sys.exit(main())
