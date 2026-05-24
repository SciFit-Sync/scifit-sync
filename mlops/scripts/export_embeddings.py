"""크롤링 → 청킹 → 임베딩까지 실행 후 결과를 JSONL.gz 파일로 export.

단일 진입점에서 **default 모드(단일 모델)** 와 **test 모드(멀티 모델 + auto eval)** 를
모두 처리한다. 산출물 경로는 `--batch-tag` 기반으로 자동 결정된다.

사용법:
    # Default — 단일 모델 임베딩 (운영용)
    python -m mlops.scripts.export_embeddings \
        --model bge-large \
        --batch-tag 2k_round1 \
        --max-papers 2000 \
        --update-manifest

    # Test — 모델 3개 동시 + 자동 평가 (A/B 비교용)
    python -m mlops.scripts.export_embeddings \
        --test \
        --batch-tag 2k_round1 \
        --max-papers 2000 \
        --goldset mlops/eval/gold_set.jsonl \
        --reuse-chunks

산출물 경로 (자동 결정):
    mlops/data/chunks/<batch-tag>.jsonl.gz                    # 모델 간 공유 입력
    mlops/data/chunks/<batch-tag>.jsonl.gz.meta.json          # 사이드카 (version, paper_count, updated_at)
    mlops/data/emb_<model-key>/<batch-tag>.jsonl.gz           # Chunk 메타 + embedding
    mlops/data/emb_<model-key>/<batch-tag>_timing.json        # 모델/시간/디바이스 사이드카
    mlops/eval/reports/<batch-tag>_<model-key>.md             # test 모드 평가 리포트

운영 노트 (incremental chunks cache):
- 같은 --batch-tag로 동시에 두 번 띄우지 말 것. _save_chunks_atomic이 부분 쓰기는
  방어하지만 lost update는 막지 못한다.
- OpenAlex daily quota는 midnight UTC (한국 09:00)에 리셋되므로 부족분 fill을
  새 quota로 돌리려면 그 시각 이후에 재실행.
- `<batch-tag>.jsonl.gz.invalid.<timestamp>` 파일이 생겼다면 schema/version
  mismatch fallback 흔적. 진단 후 삭제 가능.
"""

import argparse
import contextlib
import gzip
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.chunker import chunk_papers
from mlops.pipeline.config import DATA_DIR, MANIFEST_PATH, MAX_PAPERS_PER_RUN
from mlops.pipeline.crawler import crawl_papers
from mlops.pipeline.embedder import (
    _resolve_device,
    embed_chunks_with_spec,
    log_device_status,
)
from mlops.pipeline.manifest import Manifest
from mlops.pipeline.models import Chunk
from mlops.pipeline.specs import (
    DEFAULT_MODEL_KEY,
    EMBEDDING_MODELS,
    EmbeddingModelSpec,
    get_spec,
    list_test_targets,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

ACTIVE_SOURCES: set[str] = {"pmc", "europepmc"}  # Phase 1


# ── 산출물 경로 helpers ──────────────────────────────────────────────────


def _chunks_path(batch_tag: str) -> Path:
    return DATA_DIR / "chunks" / f"{batch_tag}.jsonl.gz"


CHUNKS_META_VERSION = 1


def _meta_path(chunks_path: Path) -> Path:
    """`<tag>.jsonl.gz` → `<tag>.jsonl.gz.meta.json`. Path.with_suffix는 마지막
    suffix를 교체하므로 name에 직접 append한다."""
    return chunks_path.parent / (chunks_path.name + ".meta.json")


def _count_unique_papers(chunks: list[Chunk]) -> int:
    """chunks가 커버하는 고유 paper 수. paper_doi 우선, 없으면 paper_pmid 사용.
    둘 다 빈 string이면 카운트에서 제외."""
    keys: set[str] = set()
    for c in chunks:
        key = c.paper_doi or c.paper_pmid
        if key:
            keys.add(key)
    return len(keys)


def _chunks_doi_set(chunks: list[Chunk]) -> set[str]:
    """캐시 chunks의 paper_doi 집합. 빈 string은 제외 — 빈 DOI를 existing_dois에
    넣으면 crawler dedup 로직을 오염시킬 위험."""
    return {c.paper_doi for c in chunks if c.paper_doi}


def _merge_chunks(old: list[Chunk], new: list[Chunk]) -> list[Chunk]:
    """기존 chunks + 신규 chunks를 paper 단위 dedup하여 합친다.

    paper_doi 우선, 없으면 paper_pmid로 key 생성. 같은 paper의 chunk는 모두 보존
    하지만 같은 paper의 신규 chunks는 통째로 폐기 (old 우선)."""
    old_keys: set[str] = set()
    for c in old:
        key = c.paper_doi or c.paper_pmid
        if key:
            old_keys.add(key)

    merged = list(old)
    for c in new:
        key = c.paper_doi or c.paper_pmid
        if key and key in old_keys:
            continue
        merged.append(c)
    return merged


def _save_chunks_atomic(path: Path, chunks: list[Chunk]) -> None:
    """chunks를 gzip JSONL로 atomic 저장. 부분 쓰기 방어용 tmp + os.replace 패턴.

    중간 실패 시 원본 path 파일은 그대로 보존된다 (.tmp는 cleanup 시도, 실패해도
    무시 — 원본 무결성이 우선).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with gzip.open(tmp, "wt", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c.model_dump(), ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def _load_meta_sidecar(chunks_path: Path) -> dict | None:
    """사이드카 메타파일 로드. 없거나 JSON 손상 시 None — caller가 legacy 처리."""
    meta_path = _meta_path(chunks_path)
    if not meta_path.exists():
        return None
    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("사이드카 JSON 손상, legacy로 fallback: %s", meta_path)
        return None


def _write_meta_sidecar(chunks_path: Path, chunks: list[Chunk]) -> None:
    """chunks 저장 직후 호출. version + 카운트 + 시각 메타를 사이드카에 기록."""
    meta_path = _meta_path(chunks_path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    existing = _load_meta_sidecar(chunks_path) or {}
    payload = {
        "version": CHUNKS_META_VERSION,
        "chunks_path": chunks_path.name,
        "paper_count": _count_unique_papers(chunks),
        "chunk_count": len(chunks),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
    }
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _invalidate_cache(chunks_path: Path, reason: str) -> None:
    """schema mismatch/JSON 손상 시 chunks 파일과 사이드카에 .invalid.<ts> 접미사
    부여. 원본을 즉시 삭제하지 않고 흔적을 남겨 운영자가 진단할 수 있게 한다."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = f".invalid.{ts}"
    for p in (chunks_path, _meta_path(chunks_path)):
        if p.exists():
            p.rename(p.with_name(p.name + suffix))
    logger.warning("chunks 캐시 무효화 (%s): %s%s", reason, chunks_path.name, suffix)


def _emb_path(batch_tag: str, model_key: str) -> Path:
    return DATA_DIR / f"emb_{model_key}" / f"{batch_tag}.jsonl.gz"


def _timing_path(batch_tag: str, model_key: str) -> Path:
    return DATA_DIR / f"emb_{model_key}" / f"{batch_tag}_timing.json"


def _report_path(batch_tag: str, model_key: str) -> Path:
    # mlops/eval/reports/<batch-tag>_<model-key>.md
    return Path(__file__).resolve().parent.parent / "eval" / "reports" / f"{batch_tag}_{model_key}.md"


# ── chunks 직렬화 ────────────────────────────────────────────────────────


def _save_chunks(path: Path, chunks: list[Chunk]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c.model_dump(), ensure_ascii=False))
            f.write("\n")


def _load_chunks(path: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            chunks.append(Chunk(**raw))
    return chunks


# ── 모델 selection ───────────────────────────────────────────────────────


def _resolve_test_models(models_arg: str | None) -> list[EmbeddingModelSpec]:
    """test 모드 모델 선택. None이면 registry 전체."""
    if not models_arg:
        return list_test_targets()
    keys = [k.strip() for k in models_arg.split(",") if k.strip()]
    return [get_spec(k) for k in keys]


# ── timing.json ─────────────────────────────────────────────────────────


def _write_timing(
    path: Path,
    spec: EmbeddingModelSpec,
    n_chunks: int,
    batch_size: int,
    device: str,
    total_sec: float,
    started_at: datetime,
    finished_at: datetime,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "model_key": spec.key,
        "hf_name": spec.hf_name,
        "dim": spec.dim,
        "n_chunks": n_chunks,
        "batch_size": batch_size,
        "device": device,
        "total_sec": round(total_sec, 3),
        "query_prefix": spec.query_prefix,
        "normalize_embeddings": spec.normalize,
        "started_at": started_at.isoformat(timespec="seconds"),
        "finished_at": finished_at.isoformat(timespec="seconds"),
    }
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")


# ── embeddings JSONL.gz ─────────────────────────────────────────────────


def _write_embeddings(path: Path, pairs: list[tuple[Chunk, list[float]]]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with gzip.open(path, "wt", encoding="utf-8") as f:
        for chunk, vec in pairs:
            record = chunk.model_dump()
            record["embedding"] = vec
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")
            written += 1
    return written


_SHARD_SIZE = int(os.getenv("EMBED_SHARD_SIZE", "10000"))


def _embed_and_write_streaming(
    path: Path,
    chunks: list[Chunk],
    spec: "EmbeddingModelSpec",
    batch_size: int,
) -> int:
    """shard 단위로 임베딩 → 즉시 디스크 기록 → 메모리 해제.

    전체 벡터를 메모리에 누적하지 않으므로 대규모 청크셋에서 OOM을 방지한다.
    """
    import gc

    from mlops.pipeline.embedder import embed_texts_with_spec

    path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    n_shards = (len(chunks) + _SHARD_SIZE - 1) // _SHARD_SIZE
    logger.info(
        "[streaming] %d청크 → %d shards (shard_size=%d)",
        len(chunks), n_shards, _SHARD_SIZE,
    )

    with gzip.open(path, "wt", encoding="utf-8") as f:
        for shard_idx in range(n_shards):
            start = shard_idx * _SHARD_SIZE
            end = min(start + _SHARD_SIZE, len(chunks))
            shard_chunks = chunks[start:end]

            texts = [c.content for c in shard_chunks]
            vectors = embed_texts_with_spec(texts, spec, batch_size=batch_size)

            for chunk, vec in zip(shard_chunks, vectors, strict=True):
                record = chunk.model_dump()
                record["embedding"] = vec
                f.write(json.dumps(record, ensure_ascii=False))
                f.write("\n")
                written += 1

            del texts, vectors
            gc.collect()
            logger.info(
                "[streaming] shard %d/%d 완료 (%d청크 누적)",
                shard_idx + 1, n_shards, written,
            )

    return written


# ── goldset coverage 검증 ───────────────────────────────────────────────


def _goldset_coverage(
    goldset_path: Path,
    chunks: list[Chunk],
) -> tuple[set[str], set[str]]:
    """goldset의 expected_pmids ⊈ corpus pmids 여부 검사.

    Returns:
        (covered_pmids, missing_pmids).
    """
    corpus_pmids = {c.paper_pmid for c in chunks if c.paper_pmid}
    expected_pmids: set[str] = set()
    with goldset_path.open("r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue
            raw = json.loads(stripped)
            for p in raw.get("expected_pmids", []):
                if p:
                    expected_pmids.add(str(p))
    covered = expected_pmids & corpus_pmids
    missing = expected_pmids - corpus_pmids
    return covered, missing


# ── Fail-fast 사전 검증 ─────────────────────────────────────────────────


def _fail_fast(args: argparse.Namespace, parser: argparse.ArgumentParser) -> list[EmbeddingModelSpec]:
    """시작 전 사전 검증 (설계서 § 6). 실패 시 argparse.error/SystemExit.

    Returns:
        선택된 모델 spec 목록 (default: 단일, test: 복수). main이 직접 사용한다.
    """
    # 1. --batch-tag: argparse required=True가 처리
    # 2. default 모드 + --model 미지정
    if not args.test and not args.model:
        parser.error("default 모드에서는 --model <key> 가 필수입니다. 가용 key: " + ", ".join(sorted(EMBEDDING_MODELS)))
    if args.test and args.model:
        logger.warning("--test 모드에서는 --model 인자가 무시됩니다 (--models로 부분 선택 가능).")

    # 3. --model / --models registry 검증
    try:
        selected_specs = _resolve_test_models(args.models) if args.test else [get_spec(args.model)]
    except KeyError as e:
        parser.error(str(e))

    # 4-5. test 모드 + goldset 파일 검증
    if args.test:
        if not args.goldset.exists():
            parser.error(f"--goldset 파일이 존재하지 않음: {args.goldset}")
        with args.goldset.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    json.loads(stripped)
                except json.JSONDecodeError as e:
                    parser.error(f"--goldset JSON 파싱 실패 line {line_no}: {e}")

    # 6. 산출물 경로 충돌 검증 — chunks + emb_<key> 양쪽 모두
    # chunks는 reuse-chunks 의도일 때만 기존 파일이 허용된다.
    # (의도 없는데 chunks가 이미 있으면 미주의로 덮어쓸 위험이 있다.)
    if not args.overwrite:
        existing: list[Path] = []
        chunks_p = _chunks_path(args.batch_tag)
        if chunks_p.exists() and not args.reuse_chunks:
            existing.append(chunks_p)
        for spec in selected_specs:
            p = _emb_path(args.batch_tag, spec.key)
            if p.exists():
                existing.append(p)
        if existing:
            parser.error(f"산출물 이미 존재 (--overwrite 없음): {', '.join(str(p) for p in existing)}")

    # 7. --require-gpu
    if args.require_gpu:
        device = _resolve_device()
        if not device.startswith("cuda"):
            parser.error(f"--require-gpu 지정됐으나 cuda 미감지 (device={device})")

    return selected_specs


# ── Main pipeline ───────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="SciFit-Sync 임베딩 export — A/B test 지원")
    parser.add_argument(
        "--batch-tag",
        type=str,
        required=True,
        help="산출물 식별자 (산출물 파일명에 적용)",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=None,
        help=f"default 모드 단일 모델 key. 가용: {', '.join(sorted(EMBEDDING_MODELS))}",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="test 모드 — 멀티 모델 임베딩 + 자동 평가",
    )
    parser.add_argument(
        "--models",
        type=str,
        default=None,
        help="test 모드에서 부분 선택 (쉼표 구분, 생략 시 registry 전체)",
    )
    parser.add_argument(
        "--goldset",
        type=Path,
        default=Path("mlops/eval/gold_set.jsonl"),
        help="test 모드 골드셋 경로 (default: mlops/eval/gold_set.jsonl)",
    )
    parser.add_argument("--max-papers", type=int, default=MAX_PAPERS_PER_RUN)
    parser.add_argument(
        "--max-per-category",
        type=int,
        default=None,
        help="카테고리당 후보 풀 cap. 생략 시 OPENALEX_MAX_PER_CATEGORY/PUBMED_MAX_PER_CATEGORY 사용",
    )
    parser.add_argument("--min-date", default=None, help="YYYY/MM/DD")
    parser.add_argument("--max-date", default=None, help="YYYY/MM/DD")
    parser.add_argument(
        "--update-manifest",
        action="store_true",
        default=False,
        help="default 모드에서 manifest 즉시 갱신 (기본 OFF — 적재 검증 후 갱신이 안전)",
    )
    parser.add_argument(
        "--reuse-chunks",
        action="store_true",
        help="chunks/<tag>.jsonl.gz 이미 있으면 crawl/chunk 단계 skip",
    )
    parser.add_argument(
        "--chunks-only",
        action="store_true",
        help="Stage 1(crawl + chunk + save)만 실행. 임베딩 skip.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help="encode batch_size override (생략 시 spec.default_batch_size)",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="기존 산출물 덮어쓰기 허용 (기본은 거부)",
    )
    parser.add_argument(
        "--require-gpu",
        action="store_true",
        help="cuda 미감지 시 즉시 실패 (긴 작업 보호)",
    )
    parser.add_argument(
        "--strict-goldset",
        action="store_true",
        help="test 모드에서 goldset PMID 누락 1건이라도 있으면 error (default: WARNING)",
    )
    return parser


def _print_summary(summary_rows: list[dict]) -> None:
    """test 모드 종료 summary — stderr."""
    sys.stderr.write("\n=== Test 결과 ===\n")
    for row in summary_rows:
        sys.stderr.write(f"  {row['key']:<22}: 임베딩 {row['total_sec']:.1f}s / eval {row.get('eval_status', 'OK')}\n")
    sys.stderr.write(f"리포트: {DATA_DIR.parent / 'eval' / 'reports'}/<batch-tag>_*.md\n")


def _resolve_chunks(args: argparse.Namespace) -> tuple[list[Chunk], list]:
    """Stage 1 — chunks를 결정하고 manifest 업데이트용 papers를 반환.

    Returns:
        (chunks, papers_for_manifest). papers_for_manifest는 default 모드에서만
        의미가 있고 reuse 경로에서는 빈 리스트. chunks가 비어있으면 caller가
        early return해야 한다 (신규 논문 없음 / 청크 없음).
    """
    chunks_path = _chunks_path(args.batch_tag)
    if args.reuse_chunks and chunks_path.exists():
        invalid_reason: str | None = None
        chunks_loaded: list[Chunk] | None = None

        meta = _load_meta_sidecar(chunks_path)
        if meta is not None and meta.get("version") != CHUNKS_META_VERSION:
            invalid_reason = f"version mismatch ({meta.get('version')} != {CHUNKS_META_VERSION})"
        else:
            try:
                chunks_loaded = _load_chunks(chunks_path)
            except (json.JSONDecodeError, ValidationError) as e:
                invalid_reason = f"schema/JSON error: {e}"

        if invalid_reason is not None:
            _invalidate_cache(chunks_path, invalid_reason)
            chunks_loaded = None  # full crawl로 fall-through

        if chunks_loaded is not None:
            chunks = chunks_loaded
            cached_paper_count = _count_unique_papers(chunks)
            logger.info("chunks 재사용: %s (paper %d개)", chunks_path, cached_paper_count)

            shortage = max(0, args.max_papers - cached_paper_count)
            if shortage == 0:
                # legacy 캐시(사이드카 None)는 첫 정상 완료 시점에 자동 생성 (spec § 7).
                if meta is None:
                    _write_meta_sidecar(chunks_path, chunks)
                    logger.info("legacy 캐시 사이드카 자동 생성: %s", _meta_path(chunks_path))
                logger.info("캐시가 요청량(%d) 충족, crawl skip", args.max_papers)
                return chunks, []

            # ── 부족분 fill 분기 ──
            manifest = Manifest.load(MANIFEST_PATH)
            manifest_skip: set[str] = set()
            for doi, entry in manifest.papers.items():
                if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
                    manifest_skip.add(doi)
            cached_dois = _chunks_doi_set(chunks)
            existing_dois = manifest_skip | cached_dois
            logger.info(
                "부족분 fill: shortage=%d, existing_dois=%d (manifest_skip=%d, cached=%d)",
                shortage,
                len(existing_dois),
                len(manifest_skip),
                len(cached_dois),
            )

            new_papers = crawl_papers(
                max_total=shortage,
                max_per_category=args.max_per_category,
                min_date=args.min_date,
                max_date=args.max_date,
                existing_dois=existing_dois,
            )
            indexed_new = [p for p in new_papers if p.sections]
            no_section = len(new_papers) - len(indexed_new)
            logger.info(
                "부족분 크롤링: 시도 %d, 본문 확보 %d, 본문 미확보 %d",
                len(new_papers),
                len(indexed_new),
                no_section,
            )

            new_chunks = chunk_papers(indexed_new) if indexed_new else []
            merged = _merge_chunks(chunks, new_chunks)
            _save_chunks_atomic(chunks_path, merged)
            _write_meta_sidecar(chunks_path, merged)

            final_paper_count = _count_unique_papers(merged)
            if final_paper_count < args.max_papers:
                logger.warning(
                    "부족분 fill 후에도 요청량 미충족: %d/%d "
                    "(manifest_skip=%d, cached=%d, no_section=%d, 캐시까지로 임베딩 진행)",
                    final_paper_count,
                    args.max_papers,
                    len(manifest_skip),
                    len(cached_dois),
                    no_section,
                )

            # reuse 경로는 manifest를 갱신하지 않는다 (spec § 7).
            # crawl_papers는 paper별 실제 tried_sources를 반환하지 않으므로
            # ACTIVE_SOURCES 일괄 기록은 no-section paper를 다음 run에서 영구 차단한다.
            # full crawl 경로에서만 manifest를 갱신한다 (그것도 별도 follow-up 필요).
            return merged, []

    # ── full crawl 경로 (캐시 없음 또는 invalidate된 후 fall-through) ──
    manifest = Manifest.load(MANIFEST_PATH)
    existing_dois: set[str] = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            existing_dois.add(doi)
    logger.info("기존 manifest: %d건 (indexed + fully-tried)", len(existing_dois))

    papers = crawl_papers(
        max_total=args.max_papers,
        max_per_category=args.max_per_category,
        min_date=args.min_date,
        max_date=args.max_date,
        existing_dois=existing_dois,
    )
    if not papers:
        logger.info("신규 논문 없음.")
        return [], []
    indexed_papers = [p for p in papers if p.sections]
    logger.info("크롤링: 시도 %d, 본문 확보 %d", len(papers), len(indexed_papers))
    chunks = chunk_papers(indexed_papers) if indexed_papers else []
    if not chunks:
        logger.info("청크 없음.")
        return [], papers
    logger.info("크롤링 %d편 → 청크 %d개", len(indexed_papers), len(chunks))
    _save_chunks_atomic(chunks_path, chunks)
    _write_meta_sidecar(chunks_path, chunks)
    logger.info("chunks 저장: %s", chunks_path)
    return chunks, papers


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    selected_specs = _fail_fast(args, parser)

    logger.info("=== Embedding Export 시작 (batch-tag=%s, test=%s) ===", args.batch_tag, args.test)
    log_device_status(logger)

    # ── Stage 1: chunks ─────────────────────────────────────
    chunks, papers_for_manifest = _resolve_chunks(args)
    if not chunks:
        logger.info("처리할 chunks 없음. 종료.")
        return 0

    if args.chunks_only:
        logger.info("--chunks-only: Stage 1만 실행 후 종료")
        return 0

    # ── Test 모드: goldset coverage 검증 ─────────────────────
    if args.test:
        covered, missing = _goldset_coverage(args.goldset, chunks)
        if missing:
            msg = (
                f"goldset PMID 중 corpus에 없는 항목 {len(missing)}개 (covered={len(covered)}). "
                f"누락 예: {sorted(missing)[:5]}"
            )
            if args.strict_goldset:
                logger.error(msg)
                return 2
            logger.warning(msg + " — recall@10 상한이 자연 감소합니다.")

    # ── Stage 2: 모델 순회 + 임베딩 ────────────────────────
    # test 모드에서만 run_eval을 lazy import — default 모드 사용자에게 불필요한 import 비용 없음.
    if args.test:
        from mlops.eval import run_eval
    summary_rows: list[dict] = []
    for spec in selected_specs:
        emb_path = _emb_path(args.batch_tag, spec.key)
        timing_path = _timing_path(args.batch_tag, spec.key)
        batch_size = args.batch_size if args.batch_size is not None else spec.default_batch_size

        logger.info("[%s] 임베딩 시작 (n_chunks=%d, batch_size=%d)", spec.key, len(chunks), batch_size)
        device = _resolve_device()
        started_at = datetime.now(timezone.utc)
        t0 = time.time()
        try:
            if len(chunks) > _SHARD_SIZE:
                written = _embed_and_write_streaming(emb_path, chunks, spec, batch_size)
            else:
                pairs = embed_chunks_with_spec(chunks, spec, batch_size=batch_size)
                written = _write_embeddings(emb_path, pairs)
                del pairs
        except Exception:
            logger.exception("[%s] 임베딩 실패", spec.key)
            if args.test:
                summary_rows.append({"key": spec.key, "total_sec": 0.0, "eval_status": "EMBED_FAIL"})
                continue
            return 3
        total_sec = time.time() - t0
        finished_at = datetime.now(timezone.utc)
        _write_timing(
            timing_path,
            spec,
            n_chunks=written,
            batch_size=batch_size,
            device=device,
            total_sec=total_sec,
            started_at=started_at,
            finished_at=finished_at,
        )
        size_mb = emb_path.stat().st_size / (1024 * 1024)
        logger.info(
            "[%s] 임베딩 완료: %d청크 / %.2f MB / %.1fs → %s",
            spec.key,
            written,
            size_mb,
            total_sec,
            emb_path,
        )

        if args.test:
            report_path = _report_path(args.batch_tag, spec.key)
            eval_status = "OK"
            try:
                rc = run_eval.main(
                    [
                        "--goldset",
                        str(args.goldset),
                        "--output",
                        str(report_path),
                        "--retriever",
                        "inmem",
                        "--embeddings-file",
                        str(emb_path),
                        "--model-key",
                        spec.key,
                        "--retriever-name",
                        f"inmem+{spec.key}",
                    ]
                )
                if rc != 0:
                    eval_status = f"EVAL_RC={rc}"
            except Exception:
                logger.exception("[%s] eval 실패", spec.key)
                eval_status = "EVAL_FAIL"
            summary_rows.append({"key": spec.key, "total_sec": total_sec, "eval_status": eval_status})

    # ── Manifest 갱신 (default 모드 + --update-manifest + 신규 crawl) ──
    # 재사용 분기에서는 papers_for_manifest=[] 이므로 이 블록에 진입하지 않는다.
    # _resolve_chunks 내부에서 manifest를 한 번 로드했지만 지역 변수였으므로 여기서 재로드.
    if args.update_manifest and not args.test and papers_for_manifest:
        manifest = Manifest.load(MANIFEST_PATH)
        for p in papers_for_manifest:
            manifest.record_attempt(
                doi=p.meta.doi,
                pmid=p.meta.pmid or None,
                pmcid=p.meta.pmcid,
                openalex_id=p.meta.openalex_id,
                fulltext_source=p.meta.fulltext_source,
                tried_sources=list(ACTIVE_SOURCES),
            )
        manifest.save(MANIFEST_PATH)
        logger.info("manifest 갱신 완료")

    # ── Test 모드 summary ───────────────────────────────────
    if args.test:
        _print_summary(summary_rows)

    logger.info("=== Export 완료 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Backward-compat: 외부에서 default key 변경 없이 import할 수 있게 노출
__all__ = ["main", "DEFAULT_MODEL_KEY"]
