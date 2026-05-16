"""PubMed/PMC 스포츠 과학 논문 크롤러.

NCBI E-utilities API를 사용하여 논문 검색 → 메타데이터 수집 → PMC 전문 파싱.
Rate limit: API 키 없으면 3 req/s, 있으면 10 req/s.
"""

import logging
import time
import xml.etree.ElementTree as ET
from collections import defaultdict

import requests
from mlops.pipeline.config import (
    MAX_PAPERS_PER_CATEGORY,
    MAX_PAPERS_PER_RUN,
    NCBI_API_KEY,
    NCBI_BASE_URL,
    NCBI_HTTP_MAX_BACKOFF,
    NCBI_HTTP_MAX_RETRIES,
    NCBI_HTTP_TIMEOUT,
    NCBI_RATE_LIMIT,
    PMC_FULLTEXT_MAX_ATTEMPTS,
    PMC_FULLTEXT_RETRY_BACKOFF_BASE,
    PMC_FULLTEXT_RETRY_BACKOFF_MAX,
)
from mlops.pipeline.models import PaperFull, PaperMeta, PaperSection

logger = logging.getLogger(__name__)

# 추천 시스템 근거 데이터를 다양한 축으로 수집하기 위한 카테고리별 쿼리.
# 단일 광범위 쿼리는 NCBI relevance 정렬이 메타분석 한두 편에 편중되기 쉬워,
# 추천 알고리즘이 필요로 하는 세부 결정 축(볼륨/강도/빈도 등)이 비균등하게 수집된다.
# 각 카테고리에 strict 플래그가 있어 추천시스템 영역(메타분석이 거의 없는)은
# 공통 publication-type 필터를 우회한다.
SEARCH_QUERY_CATEGORIES: list[tuple[str, str, bool]] = [
    (
        "volume",
        '("resistance training") AND '
        '("training volume" OR "volume load" OR "sets per muscle group" OR "weekly sets") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "intensity",
        '("resistance training") AND '
        '("training intensity" OR "%1RM" OR "high load" OR "low load") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "frequency",
        '("resistance training") AND '
        '("training frequency" OR "weekly frequency" OR "sessions per week") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "hypertrophy_strength",
        '("resistance training" OR "strength training") AND '
        '("muscle hypertrophy" OR "muscle thickness" OR "cross-sectional area" '
        'OR "muscle strength" OR "maximal strength" OR "1RM") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "trained_status",
        '("resistance training") AND '
        '("trained individuals" OR "resistance-trained" OR "experienced lifters" '
        'OR "untrained individuals" OR "beginners" OR "novice") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "rest_interval",
        '("resistance training") AND '
        '("rest interval" OR "inter-set rest") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "failure_rir",
        '("resistance training") AND '
        '("training to failure" OR "muscular failure" OR "repetitions in reserve" OR "RIR") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "fatigue") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "exercise_order",
        '("resistance training") AND '
        '("exercise order" OR "exercise sequence") AND '
        '("muscle strength" OR "muscle hypertrophy" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "recommendation_system",
        '("exercise recommendation system" OR "fitness recommendation system" '
        'OR "workout recommendation system") AND '
        '("personalized" OR "machine learning" OR "user profile")',
        False,
    ),
    (
        "personalized_prescription",
        '("personalized exercise prescription" OR "individualized exercise program") AND '
        '("resistance training" OR "strength training") AND '
        '("humans" OR "adults")',
        False,
    ),
    # ── 프로젝트 고유 축: 도르래 보정 / 부위별 / 회복도 / Program / PO ──
    (
        "machine_vs_freeweight",
        '("resistance training") AND '
        '("machine" OR "free weight" OR "exercise machine" OR "selectorized" OR "plate loaded") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "biomechanics" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "emg_activation",
        '("resistance training" OR "strength training") AND '
        '("electromyography" OR "EMG" OR "muscle activation" OR "neural drive") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "periodization",
        '("resistance training") AND '
        '("periodization" OR "linear periodization" OR "undulating periodization" '
        'OR "block periodization") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "deload_recovery",
        '("resistance training") AND '
        '("deload" OR "recovery week" OR "training cycle" OR "tapering") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "fatigue" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "doms_recovery",
        '("resistance training") AND '
        '("delayed onset muscle soreness" OR "DOMS" OR "muscle damage" OR "exercise-induced muscle damage") AND '
        '("recovery" OR "muscle hypertrophy" OR "performance") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "older_adults",
        '("resistance training" OR "strength training") AND '
        '("older adults" OR "elderly" OR "sarcopenia" OR "aging") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "physical function") AND '
        '("humans")',
        True,
    ),
    (
        "women_resistance",
        '("resistance training" OR "strength training") AND '
        '("women" OR "female" OR "sex differences" OR "menstrual cycle") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "injury_prevention",
        '("resistance training") AND '
        '("injury prevention" OR "lower back pain" OR "shoulder impingement" '
        'OR "rotator cuff" OR "knee injury" OR "musculoskeletal injury") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "range_of_motion",
        '("resistance training") AND '
        '("range of motion" OR "ROM" OR "full range" OR "partial range" OR "lengthened position") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "tempo_tut",
        '("resistance training") AND '
        '("tempo" OR "time under tension" OR "lifting cadence" OR "movement velocity") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "contraction_mode",
        '("resistance training") AND '
        '("eccentric" OR "concentric" OR "isometric" OR "contraction mode") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "compound_isolation",
        '("resistance training") AND '
        '("compound exercise" OR "multi-joint" OR "single-joint" OR "isolation exercise") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "chest_training",
        '("resistance training") AND '
        '("bench press" OR "pectoral" OR "chest" OR "pectoralis major") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "back_training",
        '("resistance training") AND '
        '("row" OR "pull-down" OR "latissimus" OR "back exercise" OR "pull-up") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "legs_training",
        '("resistance training") AND '
        '("squat" OR "deadlift" OR "leg press" OR "quadriceps" OR "hamstring" OR "gluteus") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "shoulders_training",
        '("resistance training") AND '
        '("shoulder press" OR "overhead press" OR "deltoid" OR "lateral raise" OR "shoulder exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "arms_training",
        '("resistance training") AND '
        '("biceps curl" OR "triceps extension" OR "elbow flexion" OR "elbow extension" OR "arm exercise") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "core_training",
        '("resistance training" OR "core training") AND '
        '("abdominal" OR "trunk stability" OR "core stability" OR "rectus abdominis") AND '
        '("muscle hypertrophy" OR "muscle strength" OR "muscle activation") AND '
        '("humans" OR "adults")',
        True,
    ),
    (
        "load_progression",
        '("resistance training") AND '
        '("progressive overload" OR "load progression" OR "training progression") AND '
        '("muscle hypertrophy" OR "muscle strength") AND '
        '("humans" OR "adults")',
        True,
    ),
]

# 임상 근거 강도 보장: meta-analysis / systematic review / RCT + free full text.
# strict=False 카테고리(추천시스템·개인화처방)에는 적용하지 않는다.
COMMON_PUBLICATION_FILTER = (
    ' AND ("randomized controlled trial"[Publication Type] '
    'OR "meta-analysis"[Publication Type] '
    'OR "systematic review"[Publication Type]) '
    'AND "free full text"[Filter]'
)


_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _request_with_rate_limit(
    url: str,
    params: dict,
    max_retries: int = NCBI_HTTP_MAX_RETRIES,
    max_backoff: float = NCBI_HTTP_MAX_BACKOFF,
) -> requests.Response:
    """Rate limit 준수 + transient 에러에 대해 지수 백오프 재시도.

    Retry 대상:
      - ChunkedEncodingError: NCBI eutils가 HTTP body 도중 끊김 (WSL→NCBI 환경에서 실측 빈번)
      - ConnectionError: 일시적 connection refused/reset
      - Timeout: read timeout
      - HTTPError 429: rate limit 초과
      - HTTPError 5xx: 서버 장애 (transient)

    Retry 비대상:
      - HTTPError 4xx (404 등): 영구 에러 — 재시도 의미 없음
      - HTTP 200 + 깨진 body (JSON/XML 파싱 실패): 호출부에서 처리
    """
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY

    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if attempt == 0:
            time.sleep(NCBI_RATE_LIMIT)
        else:
            backoff = min(max_backoff, NCBI_RATE_LIMIT * (2**attempt))
            logger.warning("NCBI 요청 재시도 %d/%d (%.1fs 백오프): %s", attempt + 1, max_retries, backoff, last_exc)
            time.sleep(backoff)

        try:
            resp = requests.get(url, params=params, timeout=NCBI_HTTP_TIMEOUT)
            resp.raise_for_status()
            _ = resp.content  # body 강제 fetch — chunked 응답 중간 끊김도 여기서 raise
            return resp
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            continue
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status is not None and (status == 429 or 500 <= status < 600):
                last_exc = e
                continue
            raise

    assert last_exc is not None
    raise last_exc


def _fulltext_retry_backoff(attempt: int) -> float:
    """fulltext 함수 레벨 재시도 backoff 계산."""
    return min(PMC_FULLTEXT_RETRY_BACKOFF_MAX, PMC_FULLTEXT_RETRY_BACKOFF_BASE * (2**attempt))


def search_pmids(
    query: str,
    max_results: int = MAX_PAPERS_PER_CATEGORY,
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


def _resolve_pmc_id(pmid: str, max_attempts: int = PMC_FULLTEXT_MAX_ATTEMPTS) -> str | None:
    """PMID → PMCID 변환. JSON 파싱 실패는 재시도, PMC 미존재는 None 반환.

    HTTP layer retry(`_request_with_rate_limit`)는 transient 네트워크 에러만 잡으므로,
    HTTP 200인데 body가 깨진 케이스(JSONDecodeError)는 여기서 한 번 더 retry한다.

    Returns:
        PMCID 문자열, 또는 PMC 버전이 없으면 None.

    Raises:
        RuntimeError: 모든 재시도가 실패했을 때 (마지막 예외를 cause로 포함).
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        if attempt > 0:
            wait = _fulltext_retry_backoff(attempt - 1)
            logger.info(
                "PMC elink 재시도 %d/%d (%.1fs 대기): PMID=%s last_err=%s",
                attempt + 1,
                max_attempts,
                wait,
                pmid,
                last_exc,
            )
            time.sleep(wait)

        try:
            params = {
                "dbfrom": "pubmed",
                "db": "pmc",
                "id": pmid,
                "retmode": "json",
            }
            resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/elink.fcgi", params)
            data = resp.json()
        except requests.exceptions.JSONDecodeError as e:
            last_exc = e
            logger.warning("PMC elink JSON 파싱 실패 (시도 %d/%d): PMID=%s err=%s", attempt + 1, max_attempts, pmid, e)
            continue
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning("PMC elink HTTP 최종 실패 (시도 %d/%d): PMID=%s err=%s", attempt + 1, max_attempts, pmid, e)
            continue

        for linkset in data.get("linksets", []):
            for linksetdb in linkset.get("linksetdbs", []):
                if linksetdb.get("dbto") == "pmc":
                    links = linksetdb.get("links", [])
                    if links:
                        return str(links[0])
        # 응답은 정상이지만 PMC 링크가 없음 — 진짜 미존재. retry 무의미.
        return None

    raise RuntimeError(f"PMC elink 재시도 한도 초과: PMID={pmid}") from last_exc


def _fetch_pmc_sections(pmid: str, pmc_id: str, max_attempts: int = PMC_FULLTEXT_MAX_ATTEMPTS) -> list[PaperSection]:
    """PMCID로 PMC efetch XML을 받아 섹션 파싱. XML 파싱 실패는 재시도.

    Raises:
        RuntimeError: 모든 재시도가 실패했을 때 (마지막 예외를 cause로 포함).
    """
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        if attempt > 0:
            wait = _fulltext_retry_backoff(attempt - 1)
            logger.info(
                "PMC efetch 재시도 %d/%d (%.1fs 대기): PMID=%s PMC=%s last_err=%s",
                attempt + 1,
                max_attempts,
                wait,
                pmid,
                pmc_id,
                last_exc,
            )
            time.sleep(wait)

        try:
            params = {
                "db": "pmc",
                "id": pmc_id,
                "retmode": "xml",
            }
            resp = _request_with_rate_limit(f"{NCBI_BASE_URL}/efetch.fcgi", params)
            root = ET.fromstring(resp.content)
            return _parse_pmc_sections(root)
        except ET.ParseError as e:
            last_exc = e
            logger.warning(
                "PMC XML 파싱 실패 (시도 %d/%d): PMID=%s PMC=%s err=%s",
                attempt + 1,
                max_attempts,
                pmid,
                pmc_id,
                e,
            )
            continue
        except requests.exceptions.RequestException as e:
            last_exc = e
            logger.warning(
                "PMC efetch HTTP 최종 실패 (시도 %d/%d): PMID=%s PMC=%s err=%s",
                attempt + 1,
                max_attempts,
                pmid,
                pmc_id,
                e,
            )
            continue

    raise RuntimeError(f"PMC efetch 재시도 한도 초과: PMID={pmid} PMC={pmc_id}") from last_exc


def fetch_pmc_fulltext(pmid: str) -> list[PaperSection]:
    """PMC에서 전문 XML을 가져와 섹션별로 파싱한다.

    fulltext 회수율을 최대화하기 위한 두 단계 재시도 구조:
      1. HTTP layer (`_request_with_rate_limit`): transient 네트워크/서버 에러 재시도
      2. 함수 layer (`_resolve_pmc_id` / `_fetch_pmc_sections`): HTTP 200인데 body가
         깨져 JSON/XML 파싱이 실패하는 케이스 재시도

    모든 retry 파라미터는 config.py를 통해 환경변수로 조정 가능
    (NCBI_HTTP_MAX_RETRIES, NCBI_HTTP_MAX_BACKOFF, NCBI_HTTP_TIMEOUT,
    PMC_FULLTEXT_MAX_ATTEMPTS, PMC_FULLTEXT_RETRY_BACKOFF_BASE/_MAX).

    Args:
        pmid: PubMed ID

    Returns:
        PaperSection 리스트 (PMC 버전이 없으면 빈 리스트). HTTP 또는 파싱이 모든 재시도
        끝에 실패하면 RuntimeError를 raise하여 호출부가 abstract fallback을 결정한다.
    """
    pmc_id = _resolve_pmc_id(pmid)
    if pmc_id is None:
        logger.debug("PMC 전문 없음: PMID=%s", pmid)
        return []
    return _fetch_pmc_sections(pmid, pmc_id)


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


def _round_robin_dedup(
    per_category: list[tuple[str, list[str]]],
    existing: set[str],
    max_total: int,
) -> tuple[list[str], dict[str, set[str]]]:
    """카테고리별 PMID 리스트를 round-robin으로 dedup하며 cap까지 누적한다.

    각 round에서 카테고리를 한 바퀴 돌며 그 round 위치의 PMID를 하나씩 가져온다.
    단순 FIFO cap(앞쪽 카테고리가 cap을 모두 채우는 방식)이 카테고리 다양성을
    무너뜨리는 문제를 해결한다.

    동작 규칙:
      - 동일 PMID가 여러 카테고리에 매칭되면 카테고리 메타를 합집합으로 누적한다.
      - cap 도달 후에도 기존 PMID에 대한 카테고리 메타 추가는 계속된다 (신규 PMID만 거부).
      - existing 집합의 PMID는 어떤 경우에도 제외한다.

    Args:
        per_category: (카테고리명, 해당 카테고리에서 검색된 PMID 리스트) 튜플들.
        existing: 이미 수집된 PMID 집합 (중복 방지).
        max_total: 신규 PMID 누적 상한.

    Returns:
        (PMID 추가 순서 리스트, PMID → 카테고리명 set 매핑) 튜플.
    """
    pmid_to_categories: dict[str, set[str]] = defaultdict(set)
    pmid_order: list[str] = []

    max_len = max((len(pmids) for _, pmids in per_category), default=0)
    for i in range(max_len):
        for name, pmids in per_category:
            if i >= len(pmids):
                continue
            pmid = pmids[i]
            if pmid in existing:
                continue
            if pmid in pmid_to_categories:
                pmid_to_categories[pmid].add(name)
                continue
            if len(pmid_to_categories) >= max_total:
                continue
            pmid_order.append(pmid)
            pmid_to_categories[pmid].add(name)

    return pmid_order, dict(pmid_to_categories)


def crawl_papers(
    *,
    queries: list[tuple[str, str, bool]] | None = None,
    max_per_category: int | None = None,
    max_total: int | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    fetch_fulltext: bool = True,
    existing_pmids: set[str] | None = None,
) -> list[PaperFull]:
    """카테고리별 다중 쿼리로 논문을 크롤링한다.

    각 카테고리에서 검색된 PMID를 dedup하면서 합치고, 동일 PMID가 여러 카테고리에
    매칭되면 그 카테고리 목록을 PaperMeta.search_categories에 메타로 부여한다.
    이 메타는 청크에 전파되어 RAG 검색 단계에서 사용자 fitness_goals에 맞는
    카테고리에 가중치를 주는 용도로 활용된다.

    Args:
        queries: (카테고리명, 쿼리, strict_filter) 튜플 리스트.
            None이면 SEARCH_QUERY_CATEGORIES 기본값 사용.
            strict_filter=True인 경우 COMMON_PUBLICATION_FILTER가 append된다.
        max_per_category: 카테고리당 검색 상한.
        max_total: 전체 PMID 수집 상한 (카테고리 다양성 유지하며 cap).
        min_date / max_date: PubMed pdat 필터 (YYYY/MM/DD).
        fetch_fulltext: PMC 전문 수집 여부.
        existing_pmids: 이미 수집된 PMID 집합 (중복 방지).

    Returns:
        PaperFull 리스트 (각 PaperMeta에 search_categories 부여됨).
    """
    queries = queries or SEARCH_QUERY_CATEGORIES
    max_per_category = max_per_category or MAX_PAPERS_PER_CATEGORY
    max_total = max_total or MAX_PAPERS_PER_RUN
    existing = existing_pmids or set()

    # 1) 카테고리별 검색 결과 사전 수집
    per_category: list[tuple[str, list[str]]] = []
    for name, query, strict in queries:
        full_query = query + (COMMON_PUBLICATION_FILTER if strict else "")
        logger.info("카테고리 '%s' 검색 (strict=%s)", name, strict)
        try:
            pmids = search_pmids(full_query, max_per_category, min_date, max_date)
        except Exception as e:
            logger.warning("카테고리 '%s' 검색 실패: %s", name, e)
            continue
        per_category.append((name, pmids))
        logger.info("카테고리 '%s' 검색 결과: %d건", name, len(pmids))

    # 2) round-robin으로 dedup + cap (카테고리 다양성 유지)
    pmid_order, pmid_to_categories = _round_robin_dedup(per_category, existing, max_total)

    if not pmid_to_categories:
        logger.info("모든 카테고리에서 신규 논문 없음")
        return []

    logger.info(
        "round-robin 결과: 신규 PMID %d건 (카테고리 다중 매칭 분포: 평균 %.1f카테고리/논문)",
        len(pmid_to_categories),
        sum(len(v) for v in pmid_to_categories.values()) / len(pmid_to_categories),
    )

    metas = fetch_paper_metadata(pmid_order)

    for meta in metas:
        meta.search_categories = sorted(pmid_to_categories.get(meta.pmid, set()))

    papers: list[PaperFull] = []
    fulltext_failures = 0
    for meta in metas:
        sections = []
        if fetch_fulltext:
            try:
                sections = fetch_pmc_fulltext(meta.pmid)
            except Exception as e:
                fulltext_failures += 1
                logger.warning(
                    "전문 수집 최종 실패 — abstract fallback: PMID=%s err=%s",
                    meta.pmid,
                    e,
                )

        papers.append(PaperFull(meta=meta, sections=sections))
    if fulltext_failures:
        logger.info("전문 수집 최종 실패(abstract fallback) 누적: %d건", fulltext_failures)

    logger.info("크롤링 완료: %d건 (전문 포함 %d건)", len(papers), sum(1 for p in papers if p.sections))
    return papers
