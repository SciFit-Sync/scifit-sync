"""큐레이션 paper 명시 입력 ingest.

Spec §4.2 단일 상태머신 참조.

사용법 (cloud GPU 서버에서):
    python -m mlops.scripts.ingest_curated_pmids \\
        --provenance mlops/data/curated_provenance.json \\
        [--dry-run] [--limit N]
"""

import argparse
import contextlib
import fcntl
import gzip
import json
import logging
import os
import sys
import time
import xml.etree.ElementTree as ET
from itertools import islice
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.config import (  # noqa: E402
    ADMIN_API_TOKEN,
    API_BASE_URL,
    EUROPEPMC_BASE_URL,
    EUROPEPMC_RATE_LIMIT,
    MANIFEST_PATH,
    NCBI_API_KEY,
    NCBI_BASE_URL,
    NCBI_RATE_LIMIT,
)
from mlops.pipeline.curated import (  # noqa: E402
    ncbi_pmid_to_doi,
    normalize_doi,
    openalex_doi_lookup,
    title_keyword_overlap,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

LOCK_FILENAME = ".ingest.lock"
TITLE_OVERLAP_THRESHOLD = 0.2
EFETCH_BATCH_SIZE = 200


@contextlib.contextmanager
def acquire_lock(lock_path: Path):
    """flock 기반 advisory lock. 실패 시 BlockingIOError."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        with contextlib.suppress(Exception):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def efetch_pubmed_batch(pmids: list[str], timeout: int = 60) -> dict[str, dict]:
    """PubMed efetch로 PMID batch metadata 수집.

    Returns: {pmid: {doi, pmcid, title, abstract, publication_types, publication_year}}.
    응답에 없는 PMID는 dict에서 빠진다 (호출자가 누락 처리).
    """
    if not pmids:
        return {}
    params = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "xml",
    }
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    try:
        resp = requests.get(f"{NCBI_BASE_URL}/efetch.fcgi", params=params, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("efetch batch failed (%d PMIDs): %s", len(pmids), e)
        return {}

    result: dict[str, dict] = {}
    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as e:
        logger.warning("efetch XML parse failed: %s", e)
        return {}

    for article in root.findall(".//PubmedArticle"):
        pmid_el = article.find(".//MedlineCitation/PMID")
        if pmid_el is None or not pmid_el.text:
            continue
        pmid = pmid_el.text.strip()

        title_el = article.find(".//Article/ArticleTitle")
        title = "".join(title_el.itertext()).strip() if title_el is not None else ""

        abstract_el = article.find(".//Abstract/AbstractText")
        abstract = "".join(abstract_el.itertext()).strip() if abstract_el is not None else ""

        pub_types = [
            (pt.text or "").strip() for pt in article.findall(".//PublicationTypeList/PublicationType") if pt.text
        ]

        year_el = article.find(".//Article/Journal/JournalIssue/PubDate/Year")
        try:
            year = int(year_el.text) if year_el is not None and year_el.text else None
        except (ValueError, TypeError):
            year = None

        doi = ""
        pmcid = ""
        for aid in article.findall(".//ArticleIdList/ArticleId"):
            id_type = aid.attrib.get("IdType", "").lower()
            if id_type == "doi" and aid.text:
                doi = normalize_doi(aid.text)
            elif id_type == "pmc" and aid.text:
                pmcid = aid.text.strip().upper()

        result[pmid] = {
            "doi": doi,
            "pmcid": pmcid,
            "title": title,
            "abstract": abstract,
            "publication_types": pub_types,
            "publication_year": year,
        }
    return result


def _chunked(lst: list, n: int):
    """lst를 n개 단위 청크로 분할하는 제너레이터."""
    it = iter(lst)
    while chunk := list(islice(it, n)):
        yield chunk


def _mark_failure(paper: dict, reason: str) -> None:
    """invariant: failure_reason과 indexed=false 동시 기록 (§7.1)."""
    paper["failure_reason"] = reason
    paper["indexed"] = False


def resolve_papers(
    papers: list[dict],
    qid: str,
    query_context: str,
) -> list[dict]:
    """단일 상태머신: PMID 분기 + DOI-only 분기 + title sanity check.

    in-place로 paper["resolved_*"] / paper["failure_reason"] / paper["metadata"] 채움.
    metadata에는 publication_types, publication_year, pmcid, title, abstract 저장.
    """
    # 분기 A: PMID-bearing → efetch batch
    branch_a = [p for p in papers if p["raw_pmid"]]
    branch_b = [p for p in papers if p["raw_doi"] and not p["raw_pmid"]]

    if branch_a:
        pmids = [p["raw_pmid"] for p in branch_a]
        efetch_result: dict[str, dict] = {}
        for chunk in _chunked(pmids, EFETCH_BATCH_SIZE):
            efetch_result.update(efetch_pubmed_batch(chunk))

        if not efetch_result and pmids:
            logger.warning(
                "efetch batch returned 0 records for %d PMIDs (transient or upstream issue)",
                len(pmids),
            )

        # 누락 PMID는 single re-fetch
        missing = [pmid for pmid in pmids if pmid not in efetch_result]
        if missing:
            logger.info("efetch missing %d PMIDs, single-fetch retry", len(missing))
            for pmid in missing:
                single = efetch_pubmed_batch([pmid])
                if pmid in single:
                    efetch_result[pmid] = single[pmid]

        for paper in branch_a:
            pmid = paper["raw_pmid"]
            if pmid not in efetch_result:
                _mark_failure(paper, "efetch_not_found")
                continue
            meta = efetch_result[pmid]
            paper["metadata"] = meta
            paper["resolved_pmid"] = pmid
            paper["resolved_title"] = meta["title"]
            doi = meta["doi"]
            if not doi:
                # converter fallback
                doi = ncbi_pmid_to_doi(pmid)
            if not doi:
                _mark_failure(paper, "doi_resolution_failed")
                continue
            paper["resolved_doi"] = doi

    # 분기 B: DOI-only → OpenAlex
    for paper in branch_b:
        doi = normalize_doi(paper["raw_doi"])
        lookup = openalex_doi_lookup(doi)
        if lookup is None:
            _mark_failure(paper, "openalex_not_found")
            continue
        if not lookup["pmid"]:
            _mark_failure(paper, "no_pmid_from_openalex")
            continue
        paper["resolved_pmid"] = lookup["pmid"]
        paper["resolved_doi"] = lookup["doi"] or doi
        paper["resolved_title"] = lookup["title"]
        paper["metadata"] = {
            "doi": lookup["doi"] or doi,
            "pmcid": "",
            "title": lookup["title"],
            "abstract": "",
            "publication_types": [],
            "publication_year": lookup["publication_year"],
        }

    # title sanity check for typo-autofixed papers
    for paper in papers:
        if not paper.get("is_typo_autofixed"):
            continue
        if paper.get("failure_reason"):
            continue  # already failed
        title = paper.get("resolved_title") or ""
        overlap = title_keyword_overlap(title, query_context)
        if overlap < TITLE_OVERLAP_THRESHOLD:
            _mark_failure(paper, "title_mismatch")

    return papers


def mark_already_in_corpus(papers: list[dict], existing_dois: set[str]) -> None:
    """Step 5: identifier 해석 후 already_in_corpus 판정.

    이미 실패한 paper(failure_reason 채워진 것)는 건드리지 않음.
    """
    for paper in papers:
        if paper.get("failure_reason"):
            continue
        doi = paper.get("resolved_doi")
        if not doi:
            # Defensive: 미해결 paper인데 failure도 없는 상태 → 명시적 실패 처리
            _mark_failure(paper, "doi_resolution_failed")
            continue
        if doi in existing_dois:
            paper["already_in_corpus"] = True
            paper["indexed"] = True
        else:
            paper["already_in_corpus"] = False


def atomic_write_json(path: Path, data) -> None:
    """tmp + os.replace 패턴 (POSIX atomic)."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        tmp.unlink(missing_ok=True)
        raise


from mlops.pipeline.chunker import chunk_papers  # noqa: E402
from mlops.pipeline.embedder import embed_chunks  # noqa: E402
from mlops.pipeline.europepmc import EuropePMCClient  # noqa: E402
from mlops.pipeline.evidence import calculate_evidence_weight  # noqa: E402
from mlops.pipeline.manifest import Manifest  # noqa: E402
from mlops.pipeline.models import PaperFull, PaperMeta  # noqa: E402
from mlops.pipeline.oa_fetcher import (  # noqa: E402
    PaperRef,
    build_default_chain,
    default_source_names,
    fetch_chain,
)
from mlops.pipeline.pmc import PMCClient  # noqa: E402

ACTIVE_SOURCES = set(default_source_names())  # ["pmc", "europepmc", "openalex_pdf", "openalex_html", "unpaywall"]


def _fetch_server_dois() -> set[str]:
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        logger.warning("API_BASE_URL/ADMIN_API_TOKEN missing - server dedup 생략")
        return set()
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/dois"
    try:
        resp = requests.get(url, headers={"X-Admin-Token": ADMIN_API_TOKEN}, timeout=30)
        resp.raise_for_status()
        return set(resp.json()["data"]["dois"])
    except (requests.RequestException, KeyError, ValueError) as e:
        logger.warning("server DOI fetch failed: %s", e)
        return set()


def load_existing_dois(manifest) -> set[str]:
    """manifest 'indexed 또는 모든 active sources 시도' DOI + server DB DOI union.

    모든 DOI는 normalize_doi() 적용 후 set에 넣음.
    """
    manifest_dois = set()
    for doi, entry in manifest.papers.items():
        if entry.fulltext_source is not None or set(entry.tried_sources).issuperset(ACTIVE_SOURCES):
            manifest_dois.add(normalize_doi(doi))
    server_dois = {normalize_doi(d) for d in _fetch_server_dois()}
    return manifest_dois | server_dois


def build_paperfulls_for_ingest(
    papers: list[dict],
    pmc_client: PMCClient,
    europepmc_client: EuropePMCClient,
) -> list[PaperFull]:
    """resolved paper들에 fulltext fetch + PaperFull 구성."""
    result: list[PaperFull] = []
    chain = build_default_chain(pmc_client, europepmc_client)
    for paper in papers:
        if paper.get("failure_reason") or paper.get("already_in_corpus"):
            continue
        if not paper.get("resolved_doi") or not paper.get("resolved_pmid"):
            continue  # defensive: should be already marked failed

        meta_dict = paper.get("metadata", {})
        pmcid = meta_dict.get("pmcid") or None

        ref = PaperRef(
            doi=paper["resolved_doi"],
            pmid=paper["resolved_pmid"],
            pmcid=pmcid,
        )
        chain_result = fetch_chain(ref, chain)
        sections = chain_result.sections
        fulltext_source = chain_result.fulltext_source

        if not sections:
            paper["fulltext_ok"] = False
            _mark_failure(paper, "no_fulltext")
            continue
        paper["fulltext_ok"] = True

        pub_types = meta_dict.get("publication_types", [])
        evidence = calculate_evidence_weight(pub_types)

        paperfull = PaperFull(
            meta=PaperMeta(
                doi=paper["resolved_doi"],
                pmid=paper["resolved_pmid"],
                pmcid=pmcid,
                openalex_id="",
                title=paper["resolved_title"] or "",
                abstract=meta_dict.get("abstract", ""),
                publication_types=pub_types,
                published_year=meta_dict.get("publication_year"),
                search_categories=paper["search_categories"],
                evidence_weight=evidence,
                fulltext_source=fulltext_source,
            ),
            sections=sections,
        )
        result.append(paperfull)

    return result


def _build_api_payload(chunk_vectors: list[tuple]) -> dict:
    """initial_ingest.py와 동일한 schema."""
    return {
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
            for chunk, vec in chunk_vectors
        ]
    }


def api_ingest(chunk_vectors: list[tuple], max_retries: int = 3) -> int:
    if not API_BASE_URL or not ADMIN_API_TOKEN:
        raise RuntimeError("API_BASE_URL / ADMIN_API_TOKEN 미설정")
    payload = _build_api_payload(chunk_vectors)
    url = f"{API_BASE_URL.rstrip('/')}/api/v1/admin/rag/ingest"

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                url,
                json=payload,
                headers={"X-Admin-Token": ADMIN_API_TOKEN},
                timeout=300,
            )
            resp.raise_for_status()
            return resp.json()["data"]["upserted"]
        except requests.RequestException as e:
            last_exc = e
            if attempt < max_retries - 1:
                backoff = 2**attempt
                logger.warning(
                    "api_ingest attempt %d failed: %s. retry in %ds",
                    attempt + 1,
                    e,
                    backoff,
                )
                time.sleep(backoff)
            else:
                logger.error("api_ingest exhausted %d retries: %s", max_retries, e)
    raise last_exc  # type: ignore[misc]


def save_chunks_and_embeddings(
    chunks: list,
    chunk_vectors: list[tuple],
    batch_tag: str,
    model_key: str = "bge-large",
    data_dir: Path | None = None,
) -> None:
    """chunks와 embeddings를 export_embeddings.py 호환 포맷으로 jsonl.gz 저장.

    출력:
      <data_dir>/chunks/<batch_tag>.jsonl.gz          — chunk.model_dump() 한 줄씩
      <data_dir>/emb_<model_key>/<batch_tag>.jsonl.gz — {**chunk.model_dump(), "embedding": vec}

    같은 batch_tag로 반복 호출 시 기존 파일에 append ("at" 모드).
    """
    if data_dir is None:
        # mlops/data/ — scripts/ 의 두 단계 위
        data_dir = Path(__file__).resolve().parent.parent / "data"

    chunks_path = data_dir / "chunks" / f"{batch_tag}.jsonl.gz"
    emb_path = data_dir / f"emb_{model_key}" / f"{batch_tag}.jsonl.gz"

    chunks_path.parent.mkdir(parents=True, exist_ok=True)
    emb_path.parent.mkdir(parents=True, exist_ok=True)

    # chunks 파일 (append)
    with gzip.open(chunks_path, "at", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk.model_dump(), ensure_ascii=False))
            f.write("\n")

    # embeddings 파일 (append)
    with gzip.open(emb_path, "at", encoding="utf-8") as f:
        for chunk, vec in chunk_vectors:
            record = chunk.model_dump()
            record["embedding"] = vec
            f.write(json.dumps(record, ensure_ascii=False))
            f.write("\n")

    logger.info(
        "export-batch '%s': %d chunks → %s | %s",
        batch_tag,
        len(chunks),
        chunks_path,
        emb_path,
    )


def _is_paper_processed(paper: dict) -> bool:
    """resumability: indexed=True 또는 failure_reason 채워진 paper는 처리됨."""
    return paper.get("indexed") is True or bool(paper.get("failure_reason"))


def run(
    provenance_path: Path,
    dry_run: bool = False,
    limit: int | None = None,
    lock_path: Path | None = None,
    export_batch: str | None = None,
    embed_model: str = "bge-large",
) -> None:
    lock_path = lock_path or (provenance_path.parent / LOCK_FILENAME)

    try:
        with acquire_lock(lock_path):
            _run_locked(
                provenance_path,
                dry_run=dry_run,
                limit=limit,
                export_batch=export_batch,
                embed_model=embed_model,
            )
    except BlockingIOError:
        logger.error("Lock %s already held (run_3k.sh 또는 다른 ingest 진행 중?). 수동 재시도.", lock_path)
        sys.exit(1)


def _run_locked(
    provenance_path: Path,
    dry_run: bool,
    limit: int | None,
    export_batch: str | None = None,
    embed_model: str = "bge-large",
) -> None:
    # dry-run과 export-batch 모드는 API 호출 안 하므로 자격증명 체크 생략.
    # 실제 적재 모드일 때만 fail-fast 가드 적용.
    if not dry_run and not export_batch and (not API_BASE_URL or not ADMIN_API_TOKEN):
        logger.error("API_BASE_URL / ADMIN_API_TOKEN 미설정 — 종료")
        sys.exit(1)

    if not provenance_path.exists():
        logger.error("provenance 파일 없음: %s", provenance_path)
        sys.exit(1)
    try:
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        logger.error("provenance JSON 파싱 실패: %s", e)
        sys.exit(1)
    logger.info("provenance loaded: %d Qs", len(provenance))

    manifest = Manifest.load(MANIFEST_PATH)
    existing_dois = load_existing_dois(manifest)
    logger.info("existing_dois loaded: %d (manifest + server union, normalized)", len(existing_dois))

    pmc_client = PMCClient(
        base_url=NCBI_BASE_URL,
        api_key=NCBI_API_KEY,
        rate_limit=NCBI_RATE_LIMIT,
    )
    europepmc_client = EuropePMCClient(
        base_url=EUROPEPMC_BASE_URL,
        rate_limit=EUROPEPMC_RATE_LIMIT,
    )

    total_resolved = 0
    total_indexed = 0
    total_skipped = 0

    for qid, q_data in provenance.items():
        # 미처리 paper만 처리 (resumability)
        unprocessed = [p for p in q_data.get("papers", []) if not _is_paper_processed(p)]
        if limit is not None and total_resolved >= limit:
            break
        if not unprocessed:
            continue

        if limit is not None:
            unprocessed = unprocessed[: max(0, limit - total_resolved)]

        category = q_data.get("category", "unknown")
        # Q의 query string은 seed에서 가져와야 하지만 본 스크립트는 seed 미참조.
        # 대신 category + qid를 sanity check 컨텍스트로 사용 (typo paper는 소수라 충분).
        query_context = f"{category} {qid}"

        # Step 3 + Step 4 (identifier + title sanity)
        resolve_papers(unprocessed, qid=qid, query_context=query_context)
        # Step 5 (already_in_corpus)
        mark_already_in_corpus(unprocessed, existing_dois)
        # batch atomic write (resolved/failed 상태)
        atomic_write_json(provenance_path, provenance)

        # Step 6-9 (fulltext + chunk + embed + ingest)
        paperfulls = build_paperfulls_for_ingest(unprocessed, pmc_client, europepmc_client)
        if not paperfulls:
            total_skipped += len(unprocessed)
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        chunks = chunk_papers(paperfulls)
        if not chunks:
            for p in unprocessed:
                if p.get("fulltext_ok") and not p.get("failure_reason"):
                    _mark_failure(p, "no_fulltext")  # safety net
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        if dry_run:
            logger.info("[DRY RUN] qid=%s would ingest %d chunks", qid, len(chunks))
            total_resolved += len(unprocessed)
            continue

        try:
            chunk_vectors = embed_chunks(chunks)
        except Exception as e:
            logger.warning("embed_chunks first attempt failed for qid=%s: %s. single retry.", qid, e)
            try:
                chunk_vectors = embed_chunks(chunks)
            except Exception as e2:
                logger.error("embed_chunks retry exhausted: %s", e2)
                for p in unprocessed:
                    if p.get("fulltext_ok") and not p.get("failure_reason"):
                        _mark_failure(p, "embed_failed")
                atomic_write_json(provenance_path, provenance)
                total_resolved += len(unprocessed)
                continue

        if export_batch:
            # export 모드: chunks + embeddings를 jsonl.gz 파일로 저장, API ingest 생략
            save_chunks_and_embeddings(chunks, chunk_vectors, batch_tag=export_batch, model_key=embed_model)
            logger.info("qid=%s export: %d chunks saved", qid, len(chunks))
            total_resolved += len(unprocessed)
            continue

        try:
            upserted = api_ingest(chunk_vectors)
        except Exception as e:
            logger.error("api_ingest failed for qid=%s: %s", qid, e)
            for p in unprocessed:
                if p.get("fulltext_ok") and not p.get("failure_reason"):
                    _mark_failure(p, "api_ingest_failed")
            atomic_write_json(provenance_path, provenance)
            total_resolved += len(unprocessed)
            continue

        # api_ingest 성공: indexed=True 무조건 commit
        logger.info("qid=%s ingested %d chunks (%d upserted)", qid, len(chunks), upserted)
        for p in unprocessed:
            if p.get("fulltext_ok") and not p.get("failure_reason"):
                p["indexed"] = True
                total_indexed += 1
        for paperfull in paperfulls:
            manifest.record_attempt(
                doi=paperfull.meta.doi,
                pmid=paperfull.meta.pmid or None,
                pmcid=paperfull.meta.pmcid,
                openalex_id=paperfull.meta.openalex_id,
                fulltext_source=paperfull.meta.fulltext_source,
                tried_sources=list(ACTIVE_SOURCES),
            )

        atomic_write_json(provenance_path, provenance)
        total_resolved += len(unprocessed)

    manifest.save(MANIFEST_PATH)
    logger.info(
        "=== curated ingest done: resolved=%d indexed=%d skipped=%d ===",
        total_resolved,
        total_indexed,
        total_skipped,
    )


def _positive_int(s: str) -> int:
    v = int(s)
    if v <= 0:
        raise argparse.ArgumentTypeError("--limit must be a positive integer")
    return v


def main():
    parser = argparse.ArgumentParser(description="큐레이션 PMID/DOI 명시 입력 ingest")
    parser.add_argument("--provenance", required=True, type=Path, help="curated_provenance.json 경로 (in-place 갱신)")
    parser.add_argument(
        "--dry-run", action="store_true", help="resolve + fulltext + chunk까지만, embed/api_ingest 생략"
    )
    parser.add_argument("--limit", type=_positive_int, default=None, help="처리할 paper 상한 (smoke test용, 양의 정수)")
    parser.add_argument(
        "--export-batch",
        type=str,
        default=None,
        help=(
            "Export 모드: chunks와 embeddings를 jsonl.gz로 저장. "
            "값은 batch-tag (예: 'curated_20260524'). 자격증명 없어도 동작. "
            "출력: mlops/data/chunks/<tag>.jsonl.gz + mlops/data/emb_<model>/<tag>.jsonl.gz"
        ),
    )
    parser.add_argument(
        "--embed-model",
        type=str,
        default="bge-large",
        help="embedding 모델 키 (default: bge-large). export-batch 모드에서만 사용",
    )
    args = parser.parse_args()
    run(
        args.provenance,
        dry_run=args.dry_run,
        limit=args.limit,
        export_batch=args.export_batch,
        embed_model=args.embed_model,
    )


if __name__ == "__main__":
    main()
