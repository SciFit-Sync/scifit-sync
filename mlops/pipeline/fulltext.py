"""Cascading fulltext orchestrator.

각 paper에 대해 본문 확보 소스를 순서대로 시도하고 첫 SUCCESS에서 멈춘다.
Phase 1: PMC → Europe PMC.
Phase 2/3: bioRxiv, Unpaywall 추가 자리.

결과의 fulltext_source가 None이고 had_transient_error=True면 호출자는
manifest 기록을 건너뛰어 다음 실행에서 재시도하게 한다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from mlops.pipeline.europepmc import FulltextResult, FulltextStatus
from mlops.pipeline.models import PaperSection


class PMCFetcher(Protocol):
    def fetch(self, pmcid: str) -> FulltextResult: ...


class EuropePMCFetcher(Protocol):
    def fetch_by_pmid(self, pmid: str) -> FulltextResult: ...
    def fetch_by_doi(self, doi: str) -> FulltextResult: ...


logger = logging.getLogger(__name__)


@dataclass
class CascadingFulltextResult:
    fulltext_source: str | None
    tried_sources: list[str] = field(default_factory=list)
    sections: list[PaperSection] = field(default_factory=list)
    had_transient_error: bool = False


def fetch_cascading(
    *,
    pmcid: str | None,
    pmid: str | None,
    doi: str,
    pmc_client: PMCFetcher,
    europepmc_client: EuropePMCFetcher,
) -> CascadingFulltextResult:
    """PMC → Europe PMC 순으로 본문 시도.

    첫 SUCCESS에서 멈춤. NOT_AVAILABLE은 다음 소스로 fallthrough.
    TRANSIENT_ERROR도 cascading은 계속 진행하되 모든 소스가 transient면
    had_transient_error=True로 마크하여 호출자가 manifest 기록을 skip 할 수 있게 한다.
    """
    tried: list[str] = []
    transient_count = 0

    # Step 1: PMC
    if pmcid:
        tried.append("pmc")
        r = pmc_client.fetch(pmcid)
        if r.status == FulltextStatus.SUCCESS:
            return CascadingFulltextResult(
                fulltext_source="pmc",
                tried_sources=tried,
                sections=r.sections,
                had_transient_error=False,
            )
        if r.status == FulltextStatus.TRANSIENT_ERROR:
            transient_count += 1
            logger.warning("PMC transient error: doi=%s pmcid=%s err=%s", doi, pmcid, r.error)

    # Step 2: Europe PMC
    tried.append("europepmc")
    r = europepmc_client.fetch_by_pmid(pmid) if pmid else europepmc_client.fetch_by_doi(doi)

    if r.status == FulltextStatus.SUCCESS:
        return CascadingFulltextResult(
            fulltext_source="europepmc",
            tried_sources=tried,
            sections=r.sections,
            had_transient_error=False,
        )
    if r.status == FulltextStatus.TRANSIENT_ERROR:
        transient_count += 1
        logger.warning("EuropePMC transient error: doi=%s err=%s", doi, r.error)

    # Phase 2/3 추가 자리 (현재 비활성):
    #   - bioRxiv (DOI prefix 10.1101/)
    #   - Unpaywall (DOI → OA PDF URL → parse)

    # 모든 시도가 transient면 호출자가 manifest 미기록 → 다음 실행 재시도
    had_transient = transient_count > 0 and transient_count == len(tried)

    return CascadingFulltextResult(
        fulltext_source=None,
        tried_sources=tried,
        sections=[],
        had_transient_error=had_transient,
    )
