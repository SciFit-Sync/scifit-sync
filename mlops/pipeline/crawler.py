"""PubMed/PMC 스포츠 과학 논문 크롤러.

NCBI E-utilities API를 사용하여 논문 검색 → 메타데이터 수집 → PMC 전문 파싱.
Rate limit: API 키 없으면 3 req/s, 있으면 10 req/s.
"""

import logging
import time
import xml.etree.ElementTree as ET

import requests
from mlops.pipeline.config import (
    MAX_PAPERS_PER_RUN,
    NCBI_API_KEY,
    NCBI_BASE_URL,
    NCBI_RATE_LIMIT,
)
from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

logger = logging.getLogger(__name__)

# 스포츠 과학 관련 검색 쿼리
DEFAULT_SEARCH_QUERY = (
    "(exercise training[Title/Abstract] OR resistance training[Title/Abstract] "
    "OR strength training[Title/Abstract] OR hypertrophy[Title/Abstract] "
    "OR progressive overload[Title/Abstract]) "
    "AND (randomized controlled trial[Publication Type] OR meta-analysis[Publication Type] "
    "OR systematic review[Publication Type]) "
    "AND free full text[Filter]"
)


def _request_with_rate_limit(url: str, params: dict) -> requests.Response:
    """Rate limit을 준수하며 HTTP GET 요청."""
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    time.sleep(NCBI_RATE_LIMIT)
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    return resp


def search_pmids(
    query: str = DEFAULT_SEARCH_QUERY,
    max_results: int = MAX_PAPERS_PER_RUN,
    min_date: str | None = None,
    max_date: str | None = None,
) -> list[str]:
    """PubMed에서 쿼리 조건에 맞는 PMID 목록을 검색한다.

    Args:
        query: PubMed 검색 쿼리
        max_results: 최대 결과 수
        min_date: 최소 날짜 (YYYY/MM/DD)
        max_date: 최대 날짜 (YYYY/MM/DD)

    Returns:
        PMID 문자열 리스트
    """
    params = {
        "db": "pubmed",
        "term": query,
        "retmax": max_results,
        "retmode": "json",
        "sort": "relevance",
    }
    if min_date:
        params["mindate"] = min_date
        params["datetype"] = "pdat"
    if max_date:
        params["maxdate"] = max_date

    logger.info("PubMed 검색: max_results=%d, min_date=%s", max_results, min_date)
    resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/esearch.fcgi", params)
    data = resp.json()

    pmids = data.get("esearchresult", {}).get("idlist", [])
    logger.info("검색 결과: %d건 (총 %s건 중)", len(pmids), data.get("esearchresult", {}).get("count", "?"))
    return pmids


def fetch_paper_metadata(pmids: list[str]) -> list[PaperMeta]:
    """PMID 목록으로 논문 메타데이터를 일괄 조회한다.

    Args:
        pmids: PMID 문자열 리스트 (최대 200개씩 배치)

    Returns:
        PaperMeta 리스트
    """
    results: list[PaperMeta] = []
    batch_size = 200

    for i in range(0, len(pmids), batch_size):
        batch = pmids[i : i + batch_size]
        params = {
            "db": "pubmed",
            "id": ",".join(batch),
            "retmode": "xml",
            "rettype": "abstract",
        }

        resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/efetch.fcgi", params)
        root = ET.fromstring(resp.content)

        for article in root.findall(".//PubmedArticle"):
            meta = _parse_pubmed_article(article)
            if meta:
                results.append(meta)

        logger.info("메타데이터 수집: %d/%d", len(results), len(pmids))

    return results


def _parse_pubmed_article(article: ET.Element) -> PaperMeta | None:
    """PubmedArticle XML 요소에서 메타데이터를 추출한다."""
    try:
        medline = article.find(".//MedlineCitation")
        if medline is None:
            return None

        pmid_el = medline.find("PMID")
        pmid = pmid_el.text if pmid_el is not None else ""

        article_el = medline.find("Article")
        if article_el is None:
            return None

        # 제목
        title_el = article_el.find("ArticleTitle")
        title = _get_text(title_el)

        # 저자
        authors = []
        for author in article_el.findall(".//Author"):
            last = author.findtext("LastName", "")
            first = author.findtext("ForeName", "")
            if last:
                authors.append(f"{last} {first}".strip())
        authors_str = ", ".join(authors[:10])  # 최대 10명
        if len(authors) > 10:
            authors_str += " et al."

        # 저널
        journal_el = article_el.find(".//Journal/Title")
        journal = journal_el.text if journal_el is not None else ""

        # 출판 연도
        year_el = article_el.find(".//Journal/JournalIssue/PubDate/Year")
        year = int(year_el.text) if year_el is not None and year_el.text else None

        # DOI
        doi = ""
        for eid in article.findall(".//ArticleIdList/ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text or ""
                break

        # 초록
        abstract_parts = []
        for abs_text in article_el.findall(".//Abstract/AbstractText"):
            label = abs_text.get("Label", "")
            text = _get_text(abs_text)
            if label:
                abstract_parts.append(f"{label}: {text}")
            else:
                abstract_parts.append(text)
        abstract = " ".join(abstract_parts)

        return PaperMeta(
            pmid=pmid,
            title=title,
            authors=authors_str,
            journal=journal,
            published_year=year,
            doi=doi,
            abstract=abstract,
        )
    except Exception:
        logger.warning("논문 파싱 실패: %s", ET.tostring(article, encoding="unicode")[:200])
        return None


def _get_text(el: ET.Element | None) -> str:
    """XML 요소의 전체 텍스트를 추출 (하위 태그 포함)."""
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def fetch_pmc_fulltext(pmid: str) -> list[PaperSection]:
    """PMC에서 전문 XML을 가져와 섹션별로 파싱한다.

    Args:
        pmid: PubMed ID

    Returns:
        PaperSection 리스트 (전문이 없으면 빈 리스트)
    """
    # PMID → PMCID 변환
    params = {
        "dbfrom": "pubmed",
        "db": "pmc",
        "id": pmid,
        "retmode": "json",
    }
    resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/elink.fcgi", params)
    data = resp.json()

    pmc_ids = []
    for linkset in data.get("linksets", []):
        for linksetdb in linkset.get("linksetdbs", []):
            if linksetdb.get("dbto") == "pmc":
                pmc_ids.extend(str(lid) for lid in linksetdb.get("links", []))

    if not pmc_ids:
        logger.debug("PMC 전문 없음: PMID=%s", pmid)
        return []

    pmc_id = pmc_ids[0]

    # PMC 전문 XML 가져오기
    params = {
        "db": "pmc",
        "id": pmc_id,
        "retmode": "xml",
    }
    resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/efetch.fcgi", params)
    root = ET.fromstring(resp.content)

    return _parse_pmc_sections(root)


def _parse_pmc_sections(root: ET.Element) -> list[PaperSection]:
    """PMC XML에서 본문 섹션을 추출한다."""
    sections: list[PaperSection] = []

    body = root.find(".//body")
    if body is None:
        return sections

    for sec in body.findall(".//sec"):
        title_el = sec.find("title")
        section_name = title_el.text.strip() if title_el is not None and title_el.text else "Untitled"

        paragraphs = []
        for p in sec.findall("p"):
            text = _get_text(p)
            if text:
                paragraphs.append(text)

        content = "\n".join(paragraphs)
        if content.strip():
            sections.append(PaperSection(name=section_name, content=content))

    return sections


def crawl_papers(
    query: str = DEFAULT_SEARCH_QUERY,
    max_results: int = MAX_PAPERS_PER_RUN,
    min_date: str | None = None,
    max_date: str | None = None,
    fetch_fulltext: bool = True,
    existing_pmids: set[str] | None = None,
) -> list[PaperFull]:
    """논문 크롤링 메인 함수: 검색 → 메타데이터 → 전문 수집.

    Args:
        query: PubMed 검색 쿼리
        max_results: 최대 논문 수
        min_date: 최소 출판 날짜 (YYYY/MM/DD)
        max_date: 최대 출판 날짜 (YYYY/MM/DD)
        fetch_fulltext: PMC 전문 수집 여부
        existing_pmids: 이미 수집된 PMID 집합 (중복 방지)

    Returns:
        PaperFull 리스트
    """
    existing = existing_pmids or set()

    # 1. PMID 검색
    pmids = search_pmids(query, max_results, min_date, max_date)
    new_pmids = [p for p in pmids if p not in existing]
    logger.info("신규 논문: %d건 (기존 %d건 제외)", len(new_pmids), len(pmids) - len(new_pmids))

    if not new_pmids:
        return []

    # 2. 메타데이터 수집
    metas = fetch_paper_metadata(new_pmids)

    # 3. 전문 수집 (선택)
    papers: list[PaperFull] = []
    for meta in metas:
        sections = []
        if fetch_fulltext:
            try:
                sections = fetch_pmc_fulltext(meta.pmid)
            except Exception:
                logger.warning("전문 수집 실패: PMID=%s", meta.pmid)

        papers.append(PaperFull(meta=meta, sections=sections))

    logger.info("크롤링 완료: %d건 (전문 포함 %d건)", len(papers), sum(1 for p in papers if p.sections))
    return papers
