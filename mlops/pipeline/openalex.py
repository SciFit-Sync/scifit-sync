"""OpenAlex search 어댑터.

OpenAlex API(https://api.openalex.org)로 카테고리별 논문을 검색하고
PaperMeta 리스트로 정규화한다. mailto polite pool을 사용해 우선순위 큐로 처리됨.

검색 전략:
  - concept ID 필터 + keyword search 조합
  - filter: type:article, open_access.is_oa:true, language:en
  - per_page 최대 200, cursor pagination
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from mlops.pipeline.models import PaperMeta

logger = logging.getLogger(__name__)

DEFAULT_PER_PAGE = 200
# polite pool 상한은 10 req/s지만 mailto는 공유 IP 풀로 처리되어 다른 사용자 트래픽에
# 같이 throttle 된다. 0.5s 간격 정도가 sustained 호출에서 429를 회피할 수 있는 보수선.
DEFAULT_RATE_LIMIT = 0.5
DEFAULT_MAX_RETRIES = 5

# 429 전용 백오프 시퀀스(초). 폴라이트 풀 throttle은 짧은 지수 백오프로 회복되지 않으므로
# 단계적 고정 시퀀스를 사용. Retry-After 헤더가 있으면 그 값이 우선.
_RATE_LIMIT_BACKOFF_SCHEDULE = (5.0, 15.0, 30.0, 60.0, 60.0)
_MAX_RETRY_AFTER_SECONDS = 120.0  # 비정상적으로 큰 Retry-After 상한.

_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _parse_retry_after(resp: requests.Response | None) -> float | None:
    """429 응답의 Retry-After 헤더를 초 단위로 파싱. delta-seconds만 지원."""
    if resp is None:
        return None
    value = resp.headers.get("Retry-After") if hasattr(resp, "headers") else None
    if not value:
        return None
    try:
        seconds = float(str(value).strip())
    except ValueError:
        return None
    if seconds <= 0:
        return None
    return min(seconds, _MAX_RETRY_AFTER_SECONDS)


def _compute_backoff(
    attempt: int,
    *,
    is_rate_limit: bool,
    rate_limit: float,
    retry_after: float | None,
) -> float:
    """다음 시도 전 대기 시간을 산출.

    - is_rate_limit=True (429): Retry-After > 스케줄.
    - is_rate_limit=False (5xx/transient): 지수 백오프 (기존 동작 유지).
    """
    if is_rate_limit:
        if retry_after is not None:
            return retry_after
        idx = min(attempt - 1, len(_RATE_LIMIT_BACKOFF_SCHEDULE) - 1)
        return _RATE_LIMIT_BACKOFF_SCHEDULE[idx]
    return min(60.0, rate_limit * (2**attempt))


def _request_with_retries(
    url: str,
    params: dict,
    rate_limit: float,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> requests.Response:
    """OpenAlex 요청을 transient 에러에 대해 재시도.

    Retry 대상: ChunkedEncodingError, ConnectionError, Timeout, 429, 5xx.
    Retry 비대상: 429/5xx 외 4xx (404 등 영구 에러).

    백오프:
      - 429: Retry-After 헤더 우선, 없으면 5/15/30/60s 스케줄.
      - 5xx/transient: rate_limit × 2^attempt 지수 (상한 60s).
    """
    last_exc: Exception | None = None
    last_rate_limited = False
    last_retry_after: float | None = None

    for attempt in range(max_retries):
        if attempt == 0:
            time.sleep(rate_limit)
        else:
            backoff = _compute_backoff(
                attempt,
                is_rate_limit=last_rate_limited,
                rate_limit=rate_limit,
                retry_after=last_retry_after,
            )
            logger.warning(
                "OpenAlex 재시도 %d/%d (%.1fs 백오프, %s): %s",
                attempt + 1,
                max_retries,
                backoff,
                "429 rate limit" if last_rate_limited else "transient",
                last_exc,
            )
            time.sleep(backoff)

        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp
        except _RETRYABLE_EXCEPTIONS as e:
            last_exc = e
            last_rate_limited = False
            last_retry_after = None
            continue
        except requests.exceptions.HTTPError as e:
            status = getattr(e.response, "status_code", None)
            if status == 429:
                last_exc = e
                last_rate_limited = True
                last_retry_after = _parse_retry_after(e.response)
                continue
            if status is not None and 500 <= status < 600:
                last_exc = e
                last_rate_limited = False
                last_retry_after = None
                continue
            raise

    assert last_exc is not None
    raise last_exc


def abstract_from_inverted_index(inverted: dict[str, list[int]]) -> str:
    """OpenAlex abstract_inverted_index를 평문으로 재구성.

    inverted = {"word": [pos1, pos2, ...]} → "word1 word2 ..."
    """
    if not inverted:
        return ""

    position_word: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            position_word.append((pos, word))
    position_word.sort()
    return " ".join(word for _, word in position_word)


def parse_work(work: dict) -> PaperMeta | None:
    """OpenAlex work 객체를 PaperMeta로 정규화.

    DOI가 없으면 None 반환 (폐기 신호) — DOI primary key 정책.
    """
    raw_doi = work.get("doi")
    if not raw_doi:
        logger.debug("OpenAlex work에 DOI 없음, 폐기: %s", work.get("id"))
        return None

    doi = raw_doi.replace("https://doi.org/", "").strip()
    if not doi:
        return None

    ids = work.get("ids", {}) or {}
    pmid_url = ids.get("pmid", "") or ""
    pmcid_url = ids.get("pmcid", "") or ""
    openalex_url = ids.get("openalex", "") or work.get("id", "") or ""

    pmid = pmid_url.rsplit("/", 1)[-1] if pmid_url else None
    pmcid = pmcid_url.rsplit("/", 1)[-1] if pmcid_url else None
    openalex_id = openalex_url.rsplit("/", 1)[-1] if openalex_url else None

    authors_list = [
        a.get("author", {}).get("display_name", "") for a in (work.get("authorships") or []) if a.get("author")
    ][:10]
    authors = ", ".join(filter(None, authors_list))

    primary_loc = work.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    journal = source.get("display_name", "") or ""

    abstract = abstract_from_inverted_index(work.get("abstract_inverted_index") or {})
    publication_types = work.get("publication_types") or []

    return PaperMeta(
        # TODO(Task 9): pmid=""인 OpenAlex-only paper의 dedup 키 충돌은
        # DOI 기반 doc_id 도입 후 자연 해소. 지금은 PaperMeta.pmid=str 계약 유지를 위해 빈 문자열.
        pmid=pmid or "",
        title=work.get("title", "") or "",
        authors=authors,
        journal=journal,
        published_year=work.get("publication_year"),
        doi=doi,
        abstract=abstract,
        search_categories=[],
        pmcid=pmcid,
        openalex_id=openalex_id,
        publication_types=publication_types,
        # evidence_weight는 crawler.py가 publication_types를 보고 evidence.calculate_evidence_weight()로 갱신.
        # OpenAlex API는 보통 publication_types를 비워서 반환하므로, Task 10에서 PubMed 메타와 merge 후 재계산.
        evidence_weight=0.50,
        fulltext_source=None,
    )


def build_search_params(
    *,
    keywords: list[str],
    concept_ids: list[str],
    per_page: int = DEFAULT_PER_PAGE,
    mailto: str,
    cursor: str = "*",
) -> dict:
    """OpenAlex search 파라미터 빌더."""
    filter_parts = ["type:article", "open_access.is_oa:true", "language:en"]
    if concept_ids:
        filter_parts.append("concepts.id:" + "|".join(concept_ids))

    params: dict = {
        "search": " ".join(keywords) if keywords else "",
        "filter": ",".join(filter_parts),
        "per_page": per_page,
        "cursor": cursor,
    }
    if mailto:
        params["mailto"] = mailto
    return params


@dataclass
class OpenAlexClient:
    base_url: str
    mailto: str
    rate_limit: float = DEFAULT_RATE_LIMIT
    max_retries: int = DEFAULT_MAX_RETRIES

    def __post_init__(self) -> None:
        if not self.mailto:
            logger.warning("OpenAlexClient mailto 빈 문자열 — polite pool 미사용 (rate limit ↓)")

    def search(
        self,
        *,
        keywords: list[str],
        concept_ids: list[str],
        max_results: int,
        per_page: int = DEFAULT_PER_PAGE,
    ) -> list[PaperMeta]:
        """주어진 keyword/concept 조합으로 검색, 최대 max_results까지 누적."""
        results: list[PaperMeta] = []
        cursor: str | None = "*"
        prev_cursor: str | None = None
        url = f"{self.base_url}/works"
        max_pages = 100  # 65 카테고리 × 평균 5페이지의 안전 상한
        page = 0

        while cursor and len(results) < max_results and page < max_pages:
            if cursor == prev_cursor:
                logger.warning(
                    "OpenAlex cursor stuck (%r), 페이지네이션 종료. 누적 %d papers",
                    cursor,
                    len(results),
                )
                break
            prev_cursor = cursor

            params = build_search_params(
                keywords=keywords,
                concept_ids=concept_ids,
                per_page=min(per_page, max_results - len(results)),
                mailto=self.mailto,
                cursor=cursor,
            )

            resp = _request_with_retries(url, params, self.rate_limit, max_retries=self.max_retries)
            data = resp.json()

            works = data.get("results", [])
            for work in works:
                meta = parse_work(work)
                if meta is not None:
                    results.append(meta)
                if len(results) >= max_results:
                    break

            cursor = (data.get("meta") or {}).get("next_cursor")
            page += 1
            if not works:
                break

        if page >= max_pages:
            logger.warning("OpenAlex max_pages(%d) 도달, 페이지네이션 종료", max_pages)

        logger.info(
            "OpenAlex 검색 완료: keywords=%s, %d papers (DOI 보유)",
            keywords,
            len(results),
        )
        return results
