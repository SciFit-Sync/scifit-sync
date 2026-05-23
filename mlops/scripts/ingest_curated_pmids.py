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
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.curated import (
    normalize_doi,
    ncbi_pmid_to_doi,
    openalex_doi_lookup,
    title_keyword_overlap,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

import xml.etree.ElementTree as ET

import requests

from mlops.pipeline.config import NCBI_API_KEY, NCBI_BASE_URL

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
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
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
        root = ET.fromstring(resp.text)
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
            (pt.text or "").strip()
            for pt in article.findall(".//PublicationTypeList/PublicationType")
            if pt.text
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
        efetch_result = efetch_pubmed_batch(pmids)

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
