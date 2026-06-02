"""로컬 PDF ingest — 사용자가 직접 다운로드한 골드셋 보강 논문 적재.

OpenAlex / PMC / EuropePMC 체인이 실패한 paper를 PDF로 우회 보강한다.
'fulltext_source="local_pdf"'로 manifest에 기록되어 출처 추적이 가능.

사용법:
    python -m mlops.scripts.ingest_local_pdfs \\
        --pdf-dir mlops/data/local_pdfs/ \\
        --manifest mlops/data/local_pdfs/manifest.json \\
        [--dry-run] [--export-batch tag] [--embed-model bge-large]

manifest.json 포맷:
    {
      "papers": [
        {
          "filename": "myfile.pdf",
          "doi": "10.xxx/yyy",                       // doi 또는 pmid 중 하나 필수
          "pmid": "12345678",                        // optional
          "search_categories": ["hypertrophy"],      // 필수 (골드셋 카테고리 매칭)
          "publication_types": ["Meta-Analysis"],    // optional, evidence_weight 산출용
          "title": "...",                            // optional override
          "published_year": 2017,                    // optional override
          "abstract": ""                             // optional
        }
      ]
    }

메타데이터 우선순위: manifest 명시값 > PMID efetch > DOI OpenAlex > 빈 값.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.chunker import chunk_papers  # noqa: E402
from mlops.pipeline.config import (  # noqa: E402
    ADMIN_API_TOKEN,
    API_BASE_URL,
    MANIFEST_PATH,
)
from mlops.pipeline.curated import normalize_doi, openalex_doi_lookup  # noqa: E402
from mlops.pipeline.embedder import embed_chunks  # noqa: E402
from mlops.pipeline.evidence import calculate_evidence_weight  # noqa: E402
from mlops.pipeline.manifest import Manifest  # noqa: E402
from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection  # noqa: E402
from mlops.scripts.ingest_curated_pmids import (  # noqa: E402
    api_ingest,
    efetch_pubmed_batch,
    load_existing_dois,
    save_chunks_and_embeddings,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

FULLTEXT_SOURCE = "local_pdf"


def _safe_pdf_path(pdf_dir: Path, filename: str) -> Path | None:
    """pdf_dir 내부의 일반 파일만 허용. 절대경로 / `..` traversal / symlink-out 차단.

    악의적 manifest filename(`../../etc/passwd`, `/etc/shadow`, symlink-to-outside)이
    `pdf_dir` 바깥의 임의 파일을 파싱하는 것을 차단한다. resolve() 후 pdf_dir 하위인지
    검사.
    """
    if not filename or not isinstance(filename, str):
        return None
    try:
        resolved = (pdf_dir / filename).resolve()
        pdf_dir_resolved = pdf_dir.resolve()
    except (OSError, RuntimeError):
        return None
    if not resolved.is_relative_to(pdf_dir_resolved):
        return None
    return resolved


def parse_pdf(pdf_path: Path) -> list[PaperSection]:
    """로컬 PDF를 단일 'Full Text' 섹션으로 파싱.

    `curated.fetch_pdf_sections`와 같은 pypdf 흐름이며, URL 다운로드 단계만 생략한다.
    섹션 헤더 휴리스틱 분할은 하지 않는다 — chunker가 토큰 단위로 자동 분할한다.
    """
    try:
        import pypdf  # noqa: PLC0415
    except ImportError:
        logger.error("pypdf 미설치. pip install pypdf")
        return []

    try:
        reader = pypdf.PdfReader(str(pdf_path))
    except Exception as e:  # noqa: BLE001
        logger.warning("PDF 읽기 실패 %s: %s", pdf_path, e)
        return []

    texts: list[str] = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            texts.append(text)
    full_text = "\n".join(texts).strip()
    if not full_text:
        return []

    # curated.fetch_pdf_sections와 동일하게 추출 결과 유효성 검증 — pypdf가 손상·
    # linearized PDF에서 raw 바이너리를 뱉으면 폐기 (silent failure 차단).
    from mlops.pipeline.curated import _is_extraction_garbage  # noqa: PLC0415

    if _is_extraction_garbage(full_text):
        logger.warning("parse_pdf: 추출 결과가 raw PDF 바이너리/garbage — 폐기 %s", pdf_path)
        return []

    return [PaperSection(name="Full Text", content=full_text)]


def enrich_metadata(entry: dict) -> dict:
    """manifest entry + 외부 lookup으로 metadata 통합.

    우선순위: manifest 명시 > PMID efetch > DOI OpenAlex > 빈 값.
    네트워크 실패는 경고 후 manifest 값으로 진행 (graceful degradation).
    """
    doi = normalize_doi(entry.get("doi") or "")
    pmid = (entry.get("pmid") or "").strip()

    meta: dict = {
        "doi": doi,
        "pmid": pmid,
        "title": entry.get("title") or "",
        "abstract": entry.get("abstract") or "",
        "publication_types": list(entry.get("publication_types") or []),
        "published_year": entry.get("published_year"),
    }

    if pmid:
        try:
            efetch_data = efetch_pubmed_batch([pmid]).get(pmid, {})
        except Exception as e:  # noqa: BLE001
            logger.warning("efetch lookup 실패 pmid=%s: %s", pmid, e)
            efetch_data = {}
        if efetch_data:
            if not meta["title"]:
                meta["title"] = efetch_data.get("title", "")
            if not meta["abstract"]:
                meta["abstract"] = efetch_data.get("abstract", "")
            if not meta["publication_types"]:
                meta["publication_types"] = efetch_data.get("publication_types", [])
            if meta["published_year"] is None:
                meta["published_year"] = efetch_data.get("publication_year")
            if not meta["doi"]:
                # efetch가 이미 normalize하지만 암묵 계약 의존 방지 — 명시적 재정규화
                meta["doi"] = normalize_doi(efetch_data.get("doi", ""))

    if meta["doi"] and (not meta["title"] or not meta["pmid"]):
        try:
            oa = openalex_doi_lookup(meta["doi"])
        except Exception as e:  # noqa: BLE001
            logger.warning("OpenAlex lookup 실패 doi=%s: %s", meta["doi"], e)
            oa = None
        if oa:
            if not meta["title"]:
                meta["title"] = oa.get("title", "")
            if not meta["pmid"]:
                meta["pmid"] = oa.get("pmid", "")
            if meta["published_year"] is None:
                meta["published_year"] = oa.get("publication_year")

    return meta


def build_paperfull(entry: dict, pdf_dir: Path) -> PaperFull | None:
    """manifest entry 한 줄 → PaperFull. 실패 사유는 로그로 노출."""
    filename = entry.get("filename")
    if not filename:
        logger.error("manifest entry에 'filename' 없음: %s", entry)
        return None
    pdf_path = _safe_pdf_path(pdf_dir, filename)
    if pdf_path is None:
        logger.warning("path traversal 차단 / 비정상 filename: %s", filename)
        return None
    if not pdf_path.is_file():
        logger.error("PDF 파일 없음: %s", pdf_path)
        return None

    sections = parse_pdf(pdf_path)
    if not sections:
        logger.warning("PDF 본문 추출 실패: %s", pdf_path)
        return None

    meta = enrich_metadata(entry)

    # _make_doc_id가 DOI 또는 PMID 중 하나로 만들어지므로 적어도 하나는 있어야 함
    if not meta["doi"] and not meta["pmid"]:
        logger.error("DOI/PMID 둘 다 없음 — 식별자 필요: %s", filename)
        return None

    categories = list(entry.get("search_categories") or [])
    if not categories:
        logger.warning("search_categories 비어있음 (골드셋 매칭 불가): %s", filename)

    return PaperFull(
        meta=PaperMeta(
            doi=meta["doi"],
            pmid=meta["pmid"],
            pmcid=None,
            openalex_id="",
            title=meta["title"] or filename,
            abstract=meta["abstract"],
            publication_types=meta["publication_types"],
            published_year=meta["published_year"],
            search_categories=categories,
            evidence_weight=calculate_evidence_weight(meta["publication_types"]),
            fulltext_source=FULLTEXT_SOURCE,
        ),
        sections=sections,
    )


def run(
    manifest_path: Path,
    pdf_dir: Path,
    dry_run: bool,
    export_batch: str | None,
    embed_model: str,
    skip_existing: bool = True,
) -> int:
    if not manifest_path.exists():
        logger.error("manifest 파일 없음: %s", manifest_path)
        return 1
    if not pdf_dir.is_dir():
        logger.error("pdf-dir이 디렉토리가 아님: %s", pdf_dir)
        return 1
    if not dry_run and not export_batch and (not API_BASE_URL or not ADMIN_API_TOKEN):
        logger.error("API_BASE_URL / ADMIN_API_TOKEN 미설정 — 종료")
        return 1

    try:
        manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("manifest JSON 파싱 실패: %s", e)
        return 1

    entries = manifest_data.get("papers") or []
    if not entries:
        logger.error("manifest.papers가 비어있음")
        return 1
    logger.info("manifest 로드: %d entries", len(entries))

    # dedup 준비 — pipeline_manifest는 record_attempt에도 재사용
    pipeline_manifest = Manifest.load(MANIFEST_PATH)
    if skip_existing:
        existing_dois = load_existing_dois(pipeline_manifest)
        logger.info("기존 corpus DOI %d개 (manifest + server union)", len(existing_dois))
    else:
        existing_dois = set()

    seen_in_batch: set[str] = set()
    seen_pmids: set[str] = set()
    seen_filenames: set[str] = set()
    paperfulls: list[PaperFull] = []
    skipped_dup = 0
    skipped_existing = 0
    skipped_invalid = 0

    for entry in entries:
        if not isinstance(entry, dict):
            logger.warning("manifest entry가 dict가 아님 — skip: %r", entry)
            skipped_invalid += 1
            continue

        filename = entry.get("filename")
        # in-batch 같은 filename 중복: 같은 PDF를 두 번 파싱하지 않도록
        if filename and filename in seen_filenames:
            logger.warning("manifest 내 filename 중복 — skip: %s", filename)
            skipped_dup += 1
            continue

        # prefilter: manifest 명시 DOI가 이미 있으면 PDF 파싱도 생략
        explicit_doi = normalize_doi(entry.get("doi") or "")
        if explicit_doi and explicit_doi in seen_in_batch:
            logger.warning("manifest 내 DOI 중복 — skip: %s (doi=%s)", filename, explicit_doi)
            skipped_dup += 1
            continue
        if explicit_doi and explicit_doi in existing_dois:
            logger.info("이미 corpus 적재됨 — skip: %s (doi=%s)", filename, explicit_doi)
            skipped_existing += 1
            continue

        pf = build_paperfull(entry, pdf_dir)
        if not pf:
            continue

        # postfilter: enrich 후 결정된 DOI로 재검사 (PMID-only → DOI 보강된 케이스)
        final_doi = normalize_doi(pf.meta.doi)
        final_pmid = (pf.meta.pmid or "").strip()
        if final_doi:
            if final_doi in seen_in_batch:
                logger.warning("(enrich 후) DOI 중복 — skip: %s (doi=%s)", filename, final_doi)
                skipped_dup += 1
                continue
            if final_doi in existing_dois:
                logger.info("(enrich 후) 이미 corpus 적재됨 — skip: %s (doi=%s)", filename, final_doi)
                skipped_existing += 1
                continue
            seen_in_batch.add(final_doi)
        elif final_pmid:
            # PMID-only 케이스: corpus 기존 PMID 검사는 server endpoint 부재로 in-batch만.
            # 향후 `/admin/rag/pmids` 추가 시 existing_dois처럼 외부 set과도 합쳐야 함.
            if final_pmid in seen_pmids:
                logger.warning("manifest 내 PMID 중복 (DOI 미해결) — skip: %s (pmid=%s)", filename, final_pmid)
                skipped_dup += 1
                continue
            seen_pmids.add(final_pmid)

        if filename:
            seen_filenames.add(filename)
        paperfulls.append(pf)
        logger.info(
            "OK %s | doi=%s pmid=%s evidence=%.2f cats=%s",
            filename,
            pf.meta.doi or "-",
            pf.meta.pmid or "-",
            pf.meta.evidence_weight,
            pf.meta.search_categories,
        )

    logger.info(
        "dedup 결과: 적재대상=%d skip(중복)=%d skip(기존)=%d skip(invalid)=%d",
        len(paperfulls),
        skipped_dup,
        skipped_existing,
        skipped_invalid,
    )

    if not paperfulls:
        logger.warning("적재 가능한 paper 0편")
        return 1

    chunks = chunk_papers(paperfulls)
    if not chunks:
        logger.warning("청크 생성 0개")
        return 1
    logger.info("청크 총 %d개 (paper %d편)", len(chunks), len(paperfulls))

    if dry_run:
        logger.info("[DRY RUN] embed/ingest 생략")
        return 0

    chunk_vectors = embed_chunks(chunks)

    if export_batch:
        save_chunks_and_embeddings(chunks, chunk_vectors, batch_tag=export_batch, model_key=embed_model)
        logger.info("export 완료: %d chunks → batch=%s model=%s", len(chunks), export_batch, embed_model)
        return 0

    upserted = api_ingest(chunk_vectors)
    logger.info("api_ingest 완료: upserted=%d", upserted)

    for pf in paperfulls:
        if not pf.meta.doi:
            logger.warning("DOI 없음 — pipeline manifest 기록 생략 (pmid=%s)", pf.meta.pmid)
            continue
        pipeline_manifest.record_attempt(
            doi=pf.meta.doi,
            pmid=pf.meta.pmid or None,
            pmcid=pf.meta.pmcid,
            openalex_id=pf.meta.openalex_id or None,
            fulltext_source=FULLTEXT_SOURCE,
            tried_sources=[FULLTEXT_SOURCE],
        )
    pipeline_manifest.save(MANIFEST_PATH)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="로컬 PDF ingest — 골드셋 갭 보강용")
    parser.add_argument("--pdf-dir", type=Path, required=True, help="PDF 디렉토리")
    parser.add_argument("--manifest", type=Path, required=True, help="manifest.json 경로")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="parse + chunk까지만, embed/ingest 생략",
    )
    parser.add_argument(
        "--export-batch",
        type=str,
        default=None,
        help="export 모드: chunks/embeddings를 jsonl.gz로 저장 (batch_tag 지정)",
    )
    parser.add_argument(
        "--embed-model",
        type=str,
        default="bge-large",
        help="embedding 모델 키 (default: bge-large). export-batch 모드에서 사용",
    )
    parser.add_argument(
        "--skip-existing",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="이미 corpus에 적재된 DOI는 skip (default). --no-skip-existing 으로 끄면 재임베딩",
    )
    args = parser.parse_args()
    return run(
        args.manifest,
        args.pdf_dir,
        args.dry_run,
        args.export_batch,
        args.embed_model,
        skip_existing=args.skip_existing,
    )


if __name__ == "__main__":
    raise SystemExit(main())
