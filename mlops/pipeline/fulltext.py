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

from mlops.pipeline.europepmc import FulltextResult
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
    """DEPRECATED: use mlops.pipeline.oa_fetcher.fetch_chain instead.

    기존 호출자 호환을 위해 90일 유지. 내부적으로 fetch_chain 호출.
    Backward compat: tried_sources는 pmcid 없으면 'pmc' 미포함,
    had_transient_error는 '모든 시도가 transient'일 때만 True.
    """
    from mlops.pipeline.oa_fetcher import (  # noqa: PLC0415
        EuropePMCSource,
        PaperRef,
        PMCSource,
        fetch_chain,
    )
    from mlops.pipeline.oa_fetcher import (
        FulltextStatus as ChainStatus,
    )

    chain: list = []
    if pmcid:
        chain.append(PMCSource(pmc_client))
    chain.append(EuropePMCSource(europepmc_client))

    ref = PaperRef(doi=doi, pmid=pmid, pmcid=pmcid)
    chain_result = fetch_chain(ref, chain)

    tried = chain_result.tried
    had_transient = len(tried) > 0 and all(status == ChainStatus.TRANSIENT_ERROR for _, status in tried)
    return CascadingFulltextResult(
        fulltext_source=chain_result.fulltext_source,
        tried_sources=[name for name, _ in tried],
        sections=chain_result.sections,
        had_transient_error=had_transient,
    )
