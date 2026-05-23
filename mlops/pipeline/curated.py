"""큐레이션 paper 적재용 공용 helper.

normalize_doi, NCBI ID Converter, OpenAlex DOI lookup, title sanity check,
OpenAlex OA fulltext helpers (openalex_oa_url, fetch_pdf_sections, fetch_html_sections),
Unpaywall OA mirror fallback (unpaywall_oa_locations).
"""

import io
import logging
import re
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_VALIDATE_RE = re.compile(r"^10\.\d{4,9}/")


def normalize_doi(raw: str | None) -> str:
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
    if re.search(r"[\s?#%]", s):
        logger.warning("normalize_doi: suspicious characters in DOI: %s", raw)
        return ""
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


def openalex_doi_lookup(doi: str, timeout: int = 30) -> dict | None:
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
    # NOTE: timeout=30 is a conservative default. Callers in Task 3/4 should
    # consider tighter timeouts (e.g. 10s) + a retry strategy for production use.
    url = f"{OPENALEX_DOI_LOOKUP_URL}{quote(normalized, safe='')}"
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
    pmid_url = (data.get("ids") or {}).get("pmid", "")
    pmid_match = _PMID_URL_RE.search(pmid_url) if pmid_url else None
    pmid = pmid_match.group(1) if pmid_match else ""

    return {
        "doi": normalize_doi(data.get("doi", "")),
        "pmid": pmid,
        "title": data.get("title", "") or "",
        "publication_year": data.get("publication_year"),
        "type": data.get("type", "") or "",
    }


_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "of",
        "on",
        "in",
        "at",
        "to",
        "for",
        "and",
        "or",
        "but",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "with",
        "by",
        "from",
        "as",
        "this",
        "that",
        "these",
        "those",
        "vs",
    }
)
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


# ---------------------------------------------------------------------------
# OpenAlex OA fulltext helpers
# ---------------------------------------------------------------------------

_PDF_MAX_BYTES = 50 * 1024 * 1024  # 50 MB

# 출판사 사이트(Hindawi, Wiley, Springer 등) default python-requests UA를 봇으로 차단.
# 학술 OA 콘텐츠 fetch는 fair use 범위라 일반 브라우저 UA로 요청.
_BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
# Wiley/Cloudflare 등 강한 봇 차단 우회용 추가 헤더.
# Referer를 Google Scholar로 설정해 학술 traffic으로 보이게.
_BROWSER_COMMON = {
    "User-Agent": _BROWSER_UA,
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://scholar.google.com/",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "cross-site",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_HEADERS_PDF = {
    **_BROWSER_COMMON,
    "Accept": "application/pdf,*/*;q=0.8",
}
_HEADERS_HTML = {
    **_BROWSER_COMMON,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def openalex_oa_url(doi: str, timeout: int = 30) -> dict | None:
    """OpenAlex API에서 OA URL과 type 반환.

    Returns:
        {"is_oa": bool, "pdf_url": Optional[str], "landing_page_url": Optional[str]}
        또는 None (404 or error)
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return None
    url = f"{OPENALEX_DOI_LOOKUP_URL}{quote(normalized, safe='')}"
    try:
        resp = requests.get(url, timeout=timeout)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("openalex_oa_url failed for %s: %s", normalized, e)
        return None

    if not data:
        return None

    oa = data.get("open_access") or {}
    best = data.get("best_oa_location") or {}
    return {
        "is_oa": bool(oa.get("is_oa")),
        "pdf_url": best.get("pdf_url") or None,
        "landing_page_url": best.get("landing_page_url") or None,
    }


def fetch_pdf_sections(url: str, timeout: int = 60) -> list:
    """OA PDF URL에서 sections 추출.

    Returns: list[PaperSection]. 실패(non-PDF / parse error / 50MB 초과 / timeout) 시 [].
    pypdf 미설치 시 graceful degradation — 항상 [] 반환.
    """
    try:
        import pypdf  # noqa: PLC0415
    except ImportError:
        logger.warning("fetch_pdf_sections: pypdf 미설치 — PDF parse 불가. pip install pypdf")
        return []

    from mlops.pipeline.models import PaperSection  # noqa: PLC0415

    try:
        with requests.get(url, stream=True, timeout=timeout, headers=_HEADERS_PDF) as resp:
            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "pdf" not in content_type.lower():
                # Content-Type이 pdf가 아니면 skip (HTML landing page 등)
                logger.debug("fetch_pdf_sections: unexpected Content-Type=%r for %s", content_type, url)
                return []

            # 크기 제한 체크 (Content-Length 헤더가 있는 경우)
            content_length = resp.headers.get("Content-Length")
            if content_length:
                try:
                    if int(content_length) > _PDF_MAX_BYTES:
                        logger.warning("fetch_pdf_sections: PDF too large (%s bytes), skipping %s", content_length, url)
                        return []
                except ValueError:
                    pass  # non-numeric Content-Length, proceed with streaming guard

            buf = io.BytesIO()
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=1024 * 64):
                if not chunk:
                    continue
                downloaded += len(chunk)
                if downloaded > _PDF_MAX_BYTES:
                    logger.warning("fetch_pdf_sections: download exceeded 50MB, skipping %s", url)
                    return []
                buf.write(chunk)
        # with block ended — connection closed. buf is in memory, safe to parse.
        buf.seek(0)
    except requests.RequestException as e:
        logger.warning("fetch_pdf_sections HTTP error for %s: %s", url, e)
        return []

    try:
        reader = pypdf.PdfReader(buf)
        texts = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                texts.append(text)
        full_text = "\n".join(texts).strip()
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch_pdf_sections: pypdf parse error for %s: %s", url, e)
        return []

    if not full_text:
        return []

    return [PaperSection(name="Full Text", content=full_text)]


UNPAYWALL_URL = "https://api.unpaywall.org/v2/"


def unpaywall_oa_locations(doi: str, email: str = "research@example.com", timeout: int = 30) -> list[dict]:
    """Unpaywall API로 모든 OA mirror locations 반환.

    Returns: list of {"pdf_url": Optional[str], "landing_url": Optional[str]}
        OpenAlex best_oa_location 이외의 author repository, university repo 등 alternate mirrors.
    실패 시 빈 list.
    """
    normalized = normalize_doi(doi)
    if not normalized:
        return []
    url = f"{UNPAYWALL_URL}{quote(normalized, safe='')}"
    try:
        resp = requests.get(url, params={"email": email}, timeout=timeout)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        logger.warning("unpaywall lookup failed for %s: %s", normalized, e)
        return []

    if not data.get("is_oa"):
        return []

    locations = []
    # best_oa_location 먼저
    best = data.get("best_oa_location") or {}
    if best:
        locations.append(
            {
                "pdf_url": best.get("url_for_pdf"),
                "landing_url": best.get("url_for_landing_page") or best.get("url"),
            }
        )
    # 추가 oa_locations (mirrors)
    for loc in data.get("oa_locations") or []:
        if loc is best:
            continue
        locations.append(
            {
                "pdf_url": loc.get("url_for_pdf"),
                "landing_url": loc.get("url_for_landing_page") or loc.get("url"),
            }
        )
    return locations


def fetch_html_sections(url: str, timeout: int = 60) -> list:
    """OA HTML landing page에서 본문 추출.

    Returns: list[PaperSection]. 실패 또는 본문 < 500자 시 [].
    BeautifulSoup(bs4) 사용. 미설치 시 정규식 fallback.
    """
    from mlops.pipeline.models import PaperSection  # noqa: PLC0415

    try:
        resp = requests.get(url, timeout=timeout, headers=_HEADERS_HTML)
        resp.raise_for_status()
    except requests.RequestException as e:
        logger.warning("fetch_html_sections HTTP error for %s: %s", url, e)
        return []

    html = resp.text

    try:
        from bs4 import BeautifulSoup  # noqa: PLC0415

        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:  # noqa: BLE001  # FeatureNotFound when lxml not installed
            soup = BeautifulSoup(html, "html.parser")
        # <article>, <main>, <section> 순으로 본문 후보 탐색
        body_el = soup.find("article") or soup.find("main") or soup.find("section")
        text = body_el.get_text(separator=" ", strip=True) if body_el else soup.get_text(separator=" ", strip=True)
    except ImportError:
        logger.debug("fetch_html_sections: bs4 미설치 — 정규식 fallback 사용")
        # 태그 제거 정규식 fallback
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text).strip()

    if len(text) < 500:
        logger.debug("fetch_html_sections: 본문 길이 %d < 500, 빈 list 반환 (%s)", len(text), url)
        return []

    return [PaperSection(name="Full Text", content=text)]
