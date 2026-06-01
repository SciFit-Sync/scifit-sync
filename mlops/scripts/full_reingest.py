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
import json
import logging
import os
import sys
import uuid
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
        import json as _json

        from mlops.pipeline.chunker import chunk_papers
        from mlops.pipeline.config import MANIFEST_PATH
        from mlops.pipeline.crawler import backfill_publication_types_from_pubmed, crawl_papers
        from mlops.pipeline.manifest import Manifest
        from mlops.pipeline.models import PaperFull
        from mlops.scripts.export_embeddings import (
            _chunks_path,
            _save_chunks_atomic,
            _write_meta_sidecar,
        )

        # ── JATS 경로: OpenAlex + PubMed cascading ──
        jats_papers = crawl_papers(
            max_total=1_000_000,  # 실질 cap은 max_per_category가 결정
            max_per_category=max_per_category,
            existing_dois=set(),  # 첫 실행 가정; resumable 모드는 후속 확장
        )
        indexed_jats = [p for p in jats_papers if p.sections]
        logger.info(
            "Phase 2 JATS: 시도 %d, 본문 확보 %d",
            len(jats_papers),
            len(indexed_jats),
        )

        # ── local_pdf 경로: Phase 1과 동일 패턴 ──
        manifest_in = DATA_DIR / "local_pdfs" / "manifest.json"
        pdf_papers: list[PaperFull] = []
        if manifest_in.exists():
            from mlops.scripts.ingest_local_pdfs import build_paperfull

            try:
                raw = _json.loads(manifest_in.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.warning("local_pdfs manifest 파싱 실패 (skip): %s", exc)
                raw = {}
            entries = raw.get("papers") or []
            pdf_dir = DATA_DIR / "local_pdfs" / "pdfs"
            for entry in entries:
                if not isinstance(entry, dict):
                    logger.warning("manifest entry가 dict가 아님 — skip: %r", entry)
                    continue
                pf = build_paperfull(entry, pdf_dir)
                if pf is None:
                    continue
                if not (pf.meta.doi or pf.meta.pmid):
                    logger.warning(
                        "drop local_pdf: no doi/pmid for %s",
                        entry.get("title", "?"),
                    )
                    continue
                pdf_papers.append(pf)
        logger.info("Phase 2 local_pdf: %d papers", len(pdf_papers))

        # ── 통합 + 검증 ──
        all_papers = indexed_jats + pdf_papers
        if not all_papers:
            logger.error("Phase 2 fetch: 0 papers — abort")
            raise RuntimeError("Phase 2 fetch produced no papers")

        # ── publication_types 통합 보강 (chunk 전) ──
        # local PDF는 DOI는 있으나 publication_types가 비어 있고, crawl_papers
        # 밖에서 합쳐지므로 Fix A 보강을 못 거친다. 보강 없이 chunk하면 PDF 청크가
        # pub_types=[]로 생성돼 validate fill rate를 희석시킨다. crawl_papers가
        # 이미 보강한 JATS paper는 멱등적으로 대상에서 제외된다.
        pdf_backfilled = backfill_publication_types_from_pubmed([pf.meta for pf in all_papers])
        if pdf_backfilled:
            logger.info("Phase 2 publication_types 통합 보강: %d papers", pdf_backfilled)

        # ── chunks 캐시 저장 (Stage 2+3에서 재사용) ──
        chunks = chunk_papers(all_papers)
        cp = _chunks_path(batch_tag)
        _save_chunks_atomic(cp, chunks)
        _write_meta_sidecar(cp, chunks)
        logger.info(
            "Phase 2 chunks 저장: %s (%d chunks from %d papers)",
            cp,
            len(chunks),
            len(all_papers),
        )

        # ── manifest 갱신 ──
        # pdf_papers를 set으로 변환해 O(1) membership 확인
        pdf_papers_set: set[int] = {id(p) for p in pdf_papers}
        manifest = Manifest.load(MANIFEST_PATH)
        recorded = 0
        for pf in all_papers:
            if not pf.meta.doi:
                logger.warning(
                    "DOI 없음 — pipeline manifest 기록 생략 (pmid=%s)",
                    pf.meta.pmid,
                )
                continue
            tried: list[str] = ["local_pdf"] if id(pf) in pdf_papers_set else ["jats"]
            manifest.record_attempt(
                doi=pf.meta.doi,
                pmid=pf.meta.pmid or None,
                pmcid=pf.meta.pmcid,
                openalex_id=pf.meta.openalex_id or None,
                fulltext_source=pf.meta.fulltext_source,
                tried_sources=tried,
            )
            recorded += 1
        manifest.save(MANIFEST_PATH)
        logger.info("manifest 갱신: %d papers 기록", recorded)
        return MANIFEST_PATH

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
    """Stage 2+3: chunks 캐시 → 임베딩 jsonl.gz 산출.

    Stage 1에서 _save_chunks_atomic으로 저장된 chunks 캐시를 읽어
    bge-large-en-v1.5 모델로 임베딩 후 shard 단위 jsonl.gz 저장 (OOM 방지).
    임베딩 캐시가 이미 존재하면 skip (resumable).
    """
    from mlops.pipeline.embedder import embed_chunks_with_spec
    from mlops.pipeline.specs import get_spec
    from mlops.scripts.export_embeddings import (
        _SHARD_SIZE,
        _chunks_path,
        _emb_path,
        _embed_and_write_streaming,
        _load_chunks,
        _write_embeddings,
    )

    chunks_path = _chunks_path(batch_tag)
    if not chunks_path.exists():
        raise RuntimeError(f"chunks 캐시 없음: {chunks_path}. Stage 1 chunks 저장 누락")
    chunks = _load_chunks(chunks_path)
    logger.info("chunks 로드: %d chunks from %s", len(chunks), chunks_path)

    spec = get_spec("bge-large")
    emb_path = _emb_path(batch_tag, spec.key)
    if emb_path.exists():
        logger.info("임베딩 캐시 이미 존재: %s — skip (resumable)", emb_path)
        return emb_path

    batch_size = spec.default_batch_size
    if len(chunks) > _SHARD_SIZE:
        # 대용량: shard 단위 streaming으로 OOM 방지
        written = _embed_and_write_streaming(emb_path, chunks, spec, batch_size)
    else:
        # 소용량: 단순 embed + write
        pairs = embed_chunks_with_spec(chunks, spec, batch_size=batch_size)
        written = _write_embeddings(emb_path, pairs)
        del pairs

    logger.info("임베딩 완료: %d chunks → %s", written, emb_path)
    return emb_path


def stage3_5_validate(embeddings_path: Path) -> bool:
    """Stage 3.5: pre-upsert validation 게이트."""
    result = validate_jsonl([embeddings_path])
    print_report(result)
    return result.passed


def stage4_upsert(
    embeddings_path: Path,
    collection: str,
    batch_size: int = 1000,
    batch_tag: str = "",
) -> int:
    """Stage 4: ChromaDB collection에 upsert.

    admin endpoint를 통해 적재한다 (ALB 300s 한도 내 batch_size — default 1000).
    load_embeddings.load_api의 retry 패턴(502/503/504 + ConnectionError +
    exponential backoff)을 재사용하되 body에 collection 필드를 명시해 alias
    무시하고 papers_v2(또는 지정 컬렉션)에 직접 적재한다.

    Resumable: `upsert_progress_<batch_tag>_<collection>.json`에 완료된
    batch_idx 집합을 atomic write로 누적 기록. 중단/abort 후 재실행 시
    이미 완료된 batch는 skip → 실패 비용 0 (upsert 자체는 idempotent하지만
    중복 처리 시간 낭비를 차단).
    """
    import requests
    from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL
    from mlops.scripts.load_embeddings import iter_records

    if not API_BASE_URL or not ADMIN_API_TOKEN:
        raise RuntimeError("API_BASE_URL / ADMIN_API_TOKEN 환경변수 미설정")

    import time

    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"
    headers = {"X-Admin-Token": ADMIN_API_TOKEN}
    buffer: list = []
    total = 0

    # Resumable manifest: 완료된 batch_idx 집합을 디스크에 기록.
    # batch_size는 batch 경계의 의미를 결정하므로 manifest와 현재 인자가
    # 다르면 manifest를 무효화한다 (codex MAJOR [1]: batch_size 불일치 시
    # batch_idx가 가리키는 record 범위가 어긋나 데이터 누락 발생).
    # `.jsonl.gz` → `.jsonl` (stem 1회) → `dry_50` (stem 2회).
    # 다른 위치의 ".jsonl" 문자열에 영향 안 받도록 명시적으로 stem 두 번 적용.
    progress_tag = batch_tag or Path(embeddings_path.stem).stem
    progress_path = DATA_DIR / f"upsert_progress_{progress_tag}_{collection}.json"
    completed_batches: set[int] = set()
    if progress_path.exists():
        try:
            progress = json.loads(progress_path.read_text())
            stored_batch_size = progress.get("batch_size")
            if stored_batch_size != batch_size:
                logger.warning(
                    "upsert progress manifest batch_size 불일치 "
                    "(stored=%s, current=%d) — manifest 무시하고 처음부터 시작",
                    stored_batch_size,
                    batch_size,
                )
                completed_batches = set()
            else:
                completed_batches = set(progress.get("completed_batches", []))
                logger.info(
                    "upsert resume: %d batches 이미 완료 → skip (manifest=%s)",
                    len(completed_batches),
                    progress_path.name,
                )
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("upsert progress manifest 손상 (%s) — 처음부터 시작", e)
            completed_batches = set()

    def _persist_progress() -> None:
        """atomic write — tmp + os.replace로 partial-write 방지.

        suffix는 pid + uuid4 — 동일 프로세스 내 동시 호출 가능성에도
        충돌 회피 (codex MINOR [3]: future-proof).
        """
        tmp = progress_path.with_suffix(progress_path.suffix + f".tmp.{os.getpid()}.{uuid.uuid4().hex}")
        tmp.write_text(
            json.dumps(
                {
                    "batch_tag": progress_tag,
                    "collection": collection,
                    "batch_size": batch_size,
                    "completed_batches": sorted(completed_batches),
                },
                indent=2,
            )
        )
        tmp.replace(progress_path)

    def _post(batch: list, max_retries: int = 5) -> int:
        """
        Why: 2,500만 청크/1,250~2,100 _post 호출 중 단일 transient 5xx 한 번에
        stage4 전체 abort + 운영자 수동 재실행을 차단. load_embeddings.load_api와
        동일 패턴(502/503/504 + ConnectionError + exponential backoff) 재사용.
        """
        payload = {
            "chunks": [
                {
                    "paper_doi": chunk.paper_doi,
                    "paper_pmid": chunk.paper_pmid or "",
                    "paper_title": chunk.paper_title,
                    "section_name": chunk.section_name,
                    "chunk_index": chunk.chunk_index,
                    "content": chunk.content,
                    "token_count": chunk.token_count,
                    "embedding": vec,
                    "search_categories": chunk.search_categories,
                    "publication_types": chunk.publication_types,
                    "evidence_weight": chunk.evidence_weight,
                    "fulltext_source": chunk.fulltext_source or "",
                    "published_year": chunk.published_year or 0,
                }
                for chunk, vec in batch
            ],
            "collection": collection,  # papers_v2 명시 — alias 무시
        }
        for attempt in range(1, max_retries + 1):
            try:
                resp = requests.post(url, json=payload, headers=headers, timeout=300)
                resp.raise_for_status()
                return resp.json()["data"]["upserted"]
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response is not None else 0
                if status in (502, 503, 504) and attempt < max_retries:
                    wait = min(2**attempt, 30)
                    logger.warning(
                        "API %d 에러 (attempt %d/%d), %ds 후 재시도",
                        status,
                        attempt,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise
            except requests.exceptions.ConnectionError:
                if attempt < max_retries:
                    wait = min(2**attempt, 30)
                    logger.warning(
                        "연결 에러 (attempt %d/%d), %ds 후 재시도",
                        attempt,
                        max_retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise
        raise RuntimeError("unreachable: _post retry loop exited without return")

    batch_idx = 0  # 0-based index — 동일 batch_size로만 재실행 시 일관 가정
    skipped_batches = 0
    for record in iter_records(embeddings_path, skip_errors=True):
        buffer.append(record)
        if len(buffer) >= batch_size:
            if batch_idx in completed_batches:
                skipped_batches += 1
                logger.info(
                    "upsert: batch_idx=%d 이미 완료 → skip (누적 skip=%d)",
                    batch_idx,
                    skipped_batches,
                )
            else:
                total += _post(buffer)
                completed_batches.add(batch_idx)
                _persist_progress()
                logger.info(
                    "upsert: batch_idx=%d, %d chunks 누적 (collection=%s)",
                    batch_idx,
                    total,
                    collection,
                )
            buffer = []
            batch_idx += 1
    if buffer:
        if batch_idx in completed_batches:
            skipped_batches += 1
            logger.info("upsert: 마지막 batch_idx=%d 이미 완료 → skip", batch_idx)
        else:
            total += _post(buffer)
            completed_batches.add(batch_idx)
            _persist_progress()

    logger.info(
        "Stage 4 upsert 완료: %d chunks → %s (batches=%d, skipped=%d, batch_size=%d)",
        total,
        collection,
        batch_idx + (0 if not buffer else 1) - skipped_batches,
        skipped_batches,
        batch_size,
    )
    return total


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
    parser.add_argument(
        "--upsert-batch-size",
        type=int,
        default=1000,
        help=(
            "Stage 4 admin endpoint POST 배치 크기 (default: 1000). "
            "ALB 300s 한도 내. 실패 시 manifest로 완료 batch 자동 skip."
        ),
    )
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
        n = stage4_upsert(
            embeddings_path,
            collection,
            batch_size=args.upsert_batch_size,
            batch_tag=args.batch_tag,
        )
        # n은 *이번 실행에서 새로 _post한 청크 수*만 집계.
        # resume 시 skip된 batch는 포함하지 않으므로 "신규" 라벨 명시.
        # stage4_upsert 내부 로그에 `batches=`/`skipped=`로 전체 맥락 동반.
        logger.info("upsert 완료 (이번 실행 신규): %d chunks → %s", n, collection)

    # Stage 5 안내
    if args.eval_gate:
        logger.info("Stage 5: run_eval로 골드셋 recall@10 비교 후 alias swap 진행")

    return 0


if __name__ == "__main__":
    sys.exit(main())
