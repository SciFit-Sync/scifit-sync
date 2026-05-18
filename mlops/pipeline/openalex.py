"""OpenAlex search 어댑터.

OpenAlex API(https://api.openalex.org)로 카테고리별 논문을 검색하고
PaperMeta 리스트로 정규화한다. mailto polite pool을 사용해 우선순위 큐로 처리됨.

검색 전략:
  - concept ID 필터 + keyword search 조합
  - filter: type:journal-article, is_oa:true, language:en
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
DEFAULT_RATE_LIMIT = 0.1  # 초 단위 (polite pool은 매우 관대)


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
        a.get("author", {}).get("display_name", "")
        for a in (work.get("authorships") or [])
        if a.get("author")
    ][:10]
    authors = ", ".join(filter(None, authors_list))

    primary_loc = work.get("primary_location") or {}
    source = primary_loc.get("source") or {}
    journal = source.get("display_name", "") or ""

    abstract = abstract_from_inverted_index(work.get("abstract_inverted_index") or {})
    publication_types = work.get("publication_types") or []

    return PaperMeta(
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
    filter_parts = ["type:journal-article", "is_oa:true", "language:en"]
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
        url = f"{self.base_url}/works"

        while cursor and len(results) < max_results:
            time.sleep(self.rate_limit)
            params = build_search_params(
                keywords=keywords,
                concept_ids=concept_ids,
                per_page=min(per_page, max_results - len(results)),
                mailto=self.mailto,
                cursor=cursor,
            )

            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()

            works = data.get("results", [])
            for work in works:
                meta = parse_work(work)
                if meta is not None:
                    results.append(meta)
                if len(results) >= max_results:
                    break

            cursor = (data.get("meta") or {}).get("next_cursor")
            if not works:
                break

        logger.info(
            "OpenAlex 검색 완료: keywords=%s, %d papers (DOI 보유)",
            keywords,
            len(results),
        )
        return results
