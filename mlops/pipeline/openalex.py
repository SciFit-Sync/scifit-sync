"""OpenAlex search 어댑터 — mailto polite pool + cursor pagination."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from mlops.pipeline.models import PaperMeta

logger = logging.getLogger(__name__)

DEFAULT_PER_PAGE = 200
# polite pool 공유 IP throttle 때문에 0.5s 간격이 429 회피 보수선.
DEFAULT_RATE_LIMIT = 0.5
DEFAULT_MAX_RETRIES = 3
DEFAULT_CIRCUIT_BREAKER_THRESHOLD = 3

# 429 백오프(초). quota 차단은 CB가 잡으므로 짧게 — 단발성 throttle 회복용.
_RATE_LIMIT_BACKOFF_SCHEDULE = (2.0, 5.0, 10.0)
_MAX_RETRY_AFTER_SECONDS = 60.0  # 비정상적으로 큰 Retry-After 상한.

# 모듈 레벨 CB: N회 연속 실패 시 이후 search()는 즉시 빈 리스트 반환.
_circuit_breaker_consecutive_failures = 0
_circuit_breaker_tripped = False


def reset_circuit_breaker() -> None:
    """Circuit breaker 상태 초기화. 테스트/새 ingest run 시작 전 호출."""
    global _circuit_breaker_consecutive_failures, _circuit_breaker_tripped
    _circuit_breaker_consecutive_failures = 0
    _circuit_breaker_tripped = False


def is_circuit_breaker_tripped() -> bool:
    return _circuit_breaker_tripped


def _record_failure(threshold: int) -> None:
    global _circuit_breaker_consecutive_failures, _circuit_breaker_tripped
    _circuit_breaker_consecutive_failures += 1
    if _circuit_breaker_consecutive_failures >= threshold and not _circuit_breaker_tripped:
        _circuit_breaker_tripped = True
        logger.warning(
            "OpenAlex circuit breaker trip — %d회 연속 실패. "
            "이후 이 프로세스의 OpenAlex 호출은 모두 skip. "
            "다음 run 시작 전 reset_circuit_breaker() 호출 필요.",
            _circuit_breaker_consecutive_failures,
        )


def _record_success() -> None:
    global _circuit_breaker_consecutive_failures
    _circuit_breaker_consecutive_failures = 0


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
    """다음 시도 전 대기 시간 산출 (429: 스케줄 백오프, 5xx: 지수 백오프)."""
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
    """OpenAlex 요청 재시도 (429/5xx 분리 백오프 + Retry-After 파싱)."""
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
    """OpenAlex abstract_inverted_index를 평문으로 재구성."""
    if not inverted:
        return ""

    position_word: list[tuple[int, str]] = []
    for word, positions in inverted.items():
        for pos in positions:
            position_word.append((pos, word))
    position_word.sort()
    return " ".join(word for _, word in position_word)


def parse_work(work: dict) -> PaperMeta | None:
    """OpenAlex work → PaperMeta 정규화. DOI 없으면 None."""
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
    from_date: str | None = None,
    to_date: str | None = None,
) -> dict:
    """OpenAlex search 파라미터 빌더.

    from_date/to_date는 YYYY-MM-DD (OpenAlex 형식). 지정 시 publication_date
    범위 필터를 추가한다 — monthly 증분에서 OpenAlex가 매번 전(全)기간 동일
    상위 결과를 반환해 dedup으로 전량 폐기되던 문제를 해소.
    """
    filter_parts = ["type:article", "open_access.is_oa:true", "language:en"]
    if concept_ids:
        filter_parts.append("concepts.id:" + "|".join(concept_ids))
    if from_date:
        filter_parts.append(f"from_publication_date:{from_date}")
    if to_date:
        filter_parts.append(f"to_publication_date:{to_date}")

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
    circuit_breaker_threshold: int = DEFAULT_CIRCUIT_BREAKER_THRESHOLD

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
        min_date: str | None = None,
        max_date: str | None = None,
    ) -> list[PaperMeta]:
        """keyword/concept 검색, 최대 max_results까지 누적. CB trip 시 빈 리스트.

        min_date/max_date(YYYY-MM-DD)는 publication_date 범위 필터 — monthly 증분용.
        """
        if _circuit_breaker_tripped:
            return []

        results: list[PaperMeta] = []
        cursor: str | None = "*"
        prev_cursor: str | None = None
        url = f"{self.base_url}/works"
        max_pages = 100  # 65 카테고리 × 평균 5페이지의 안전 상한
        page = 0

        try:
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
                    from_date=min_date,
                    to_date=max_date,
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
        except Exception as exc:
            # 부분 성공이면 누적분을 반환하고 연속 실패 카운터를 reset한다.
            # Why: 마지막 페이지 1회 429/5xx로 그 카테고리에서 이미 받은 수백 편을
            # 통째로 버리고 CB 카운터만 올리면, 긴 런에서 OpenAlex가 조용히 영구
            # 차단(trip)되는 주원인이 된다. 일부라도 받았으면 정상 진행으로 간주.
            if results:
                logger.warning(
                    "OpenAlex search 부분 실패 — 누적 %d papers 반환 (keywords=%s): %s",
                    len(results),
                    keywords,
                    exc,
                )
                _record_success()
                return results
            # 0건이면 기존대로 실패 기록 후 raise (호출측 crawl_papers가 [] 처리)
            _record_failure(self.circuit_breaker_threshold)
            raise

        _record_success()

        if page >= max_pages:
            logger.warning("OpenAlex max_pages(%d) 도달, 페이지네이션 종료", max_pages)

        logger.info(
            "OpenAlex 검색 완료: keywords=%s, %d papers (DOI 보유)",
            keywords,
            len(results),
        )
        return results
