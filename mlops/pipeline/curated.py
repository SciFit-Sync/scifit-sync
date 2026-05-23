"""큐레이션 paper 적재용 공용 helper.

normalize_doi, NCBI ID Converter, OpenAlex DOI lookup, title sanity check.
"""

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_VALIDATE_RE = re.compile(r"^10\.\d{4,9}/")


def normalize_doi(raw: Optional[str]) -> str:
    """DOI 정규화 — idempotent.

    규칙: strip whitespace → URL prefix 제거 → lowercase → 말미 구두점(.,;) 제거.
    유효하지 않으면 빈 문자열 반환 (10.{prefix}/ 패턴 미충족).
    """
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    s = _DOI_URL_PREFIX_RE.sub("", s)
    s = s.lower()
    s = s.rstrip(".,;")
    if not _DOI_VALIDATE_RE.match(s):
        return ""
    return s


NCBI_ID_CONVERTER_URL = "https://www.ncbi.nlm.nih.gov/pmc/utils/idconv/v1.0/"


def ncbi_pmid_to_doi(pmid: str, timeout: int = 30) -> str:
    """NCBI ID Converter로 PMID → DOI 변환.

    실패 시 빈 문자열 반환. 정규화된 DOI를 돌려준다.
    """
    if not pmid:
        return ""
    try:
        resp = requests.get(
            NCBI_ID_CONVERTER_URL,
            params={"ids": pmid, "format": "json"},
            timeout=timeout,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("NCBI ID Converter failed for PMID=%s: %s", pmid, e)
        return ""

    records = data.get("records", [])
    if not records:
        return ""
    raw_doi = records[0].get("doi", "")
    return normalize_doi(raw_doi)


OPENALEX_DOI_LOOKUP_URL = "https://api.openalex.org/works/doi:"
_PMID_URL_RE = re.compile(r"https?://pubmed\.ncbi\.nlm\.nih\.gov/(\d+)")


def openalex_doi_lookup(doi: str, timeout: int = 30) -> Optional[dict]:
    """OpenAlex DOI lookup. 정상 응답이면 metadata dict 반환, 404/empty/error면 None.

    반환 dict 구조:
      {
        "doi": str (normalized),
        "pmid": str (없으면 ""),
        "title": str,
        "publication_year": int | None,
        "type": str (OpenAlex work type),
      }
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    url = f"{OPENALEX_DOI_LOOKUP_URL}{normalized}"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("OpenAlex DOI lookup failed for %s: %s", normalized, e)
        return None

    if not data:
        return None

    # PMID 추출
    pmid_url = data.get("ids", {}).get("pmid", "")
    pmid_match = _PMID_URL_RE.search(pmid_url) if pmid_url else None
    pmid = pmid_match.group(1) if pmid_match else ""

    return {
        "doi": normalize_doi(data.get("doi", "")),
        "pmid": pmid,
        "title": data.get("title", "") or "",
        "publication_year": data.get("publication_year"),
        "type": data.get("type", "") or "",
    }


_STOPWORDS = frozenset({
    "a", "an", "the", "of", "on", "in", "at", "to", "for", "and", "or", "but",
    "is", "are", "was", "were", "be", "been", "being", "have", "has", "had",
    "with", "by", "from", "as", "this", "that", "these", "those", "vs",
})
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS and len(t) > 2}


def title_keyword_overlap(title: str, context: str) -> float:
    """title과 context의 키워드 jaccard-style overlap ratio.

    title의 tokens가 context tokens 안에 얼마나 들어있는지로 계산.
    range [0.0, 1.0]. typo auto-fixed DOI의 title sanity check에 사용.
    """
    if not title or not context:
        return 0.0
    title_tokens = _tokenize(title)
    context_tokens = _tokenize(context)
    if not title_tokens:
        return 0.0
    matched = title_tokens & context_tokens
    return len(matched) / len(title_tokens)
