"""Unified OA fetcher chain.

Chain-of-Resolvers 패턴으로 다양한 OA source를 순회한다.
새 source 추가는 OASource Protocol 구현 + DEFAULT_CHAIN 등록 두 단계.

Spec: docs/superpowers/specs/2026-05-24-oa-fetcher-chain-design.md
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

from mlops.pipeline.curated import (
    fetch_html_sections,
    fetch_pdf_sections,
    openalex_oa_url,
    unpaywall_oa_locations,
)
from mlops.pipeline.europepmc import FulltextStatus as ClientFulltextStatus
from mlops.pipeline.models import PaperSection

logger = logging.getLogger(__name__)


class FulltextStatus(Enum):
    """단일 source 시도 결과 분류."""

    SUCCESS = "success"
    NOT_AVAILABLE = "not_available"  # 영구 부재 (404 등)
    TRANSIENT_ERROR = "transient"  # 일시적 (5xx, timeout)


@dataclass
class PaperRef:
    """OA source가 시도하기 위한 paper 식별자 묶음."""

    doi: str
    pmid: str | None = None
    pmcid: str | None = None
    # 사전 resolve된 OpenAlex blob (있으면 source 간 캐시 공유로 중복 API 호출 회피)
    openalex_oa: dict | None = None


@dataclass
class FulltextResult:
    """단일 source 시도 결과."""

    status: FulltextStatus
    sections: list[PaperSection] = field(default_factory=list)
    error: str | None = None


@dataclass
class ChainResult:
    """전체 chain 시도 결과."""

    fulltext_source: str | None  # 성공한 source.name, 실패 시 None
    tried: list[tuple[str, FulltextStatus]]  # per-source attempt log
    sections: list[PaperSection]
    had_transient_error: bool


@runtime_checkable
class OASource(Protocol):
    name: str  # manifest의 tried_sources에 기록될 식별자

    def try_fetch(self, ref: PaperRef) -> FulltextResult: ...


class PMCSource:
    name: str = "pmc"

    def __init__(self, pmc_client) -> None:
        self.pmc_client = pmc_client

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        if not ref.pmcid:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        result = self.pmc_client.fetch(ref.pmcid)
        return _map_client_result(result)


def _map_client_result(result) -> FulltextResult:
    """europepmc.FulltextResult → oa_fetcher.FulltextResult 매핑.

    PMC/EuropePMC client가 반환하는 FulltextResult(status=..., sections=..., error=...)를
    chain용 FulltextResult로 변환.
    """
    if result.status == ClientFulltextStatus.SUCCESS:
        return FulltextResult(
            status=FulltextStatus.SUCCESS, sections=result.sections
        )
    if result.status == ClientFulltextStatus.TRANSIENT_ERROR:
        return FulltextResult(
            status=FulltextStatus.TRANSIENT_ERROR, error=result.error
        )
    return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


class EuropePMCSource:
    name: str = "europepmc"

    def __init__(self, europepmc_client) -> None:
        self.europepmc_client = europepmc_client

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        if ref.pmid:
            result = self.europepmc_client.fetch_by_pmid(ref.pmid)
        elif ref.doi:
            result = self.europepmc_client.fetch_by_doi(ref.doi)
        else:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        return _map_client_result(result)


def fetch_chain(ref: PaperRef, sources: list[OASource]) -> ChainResult:
    """순회 sources. SUCCESS에서 stop, NOT_AVAILABLE/TRANSIENT는 다음 source로 진행."""
    tried: list[tuple[str, FulltextStatus]] = []
    had_transient = False

    for source in sources:
        try:
            result = source.try_fetch(ref)
        except Exception as e:
            logger.warning("OASource %s raised unexpected: %s", source.name, e)
            result = FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=str(e))

        tried.append((source.name, result.status))

        if result.status == FulltextStatus.TRANSIENT_ERROR:
            had_transient = True
            continue
        if result.status == FulltextStatus.SUCCESS:
            return ChainResult(
                fulltext_source=source.name,
                tried=tried,
                sections=result.sections,
                had_transient_error=had_transient,
            )
        # NOT_AVAILABLE → 다음 source

    return ChainResult(
        fulltext_source=None,
        tried=tried,
        sections=[],
        had_transient_error=had_transient,
    )


class OpenAlexPDFSource:
    """OpenAlex에서 OA PDF URL을 받아 PDF 본문 파싱."""

    name: str = "openalex_pdf"

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        oa = ref.openalex_oa if ref.openalex_oa is not None else openalex_oa_url(ref.doi)
        if oa is None or not oa.get("is_oa"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        # 다음 source(HTML)가 재사용할 수 있게 캐시
        ref.openalex_oa = oa
        pdf_url = oa.get("pdf_url")
        if not pdf_url:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        sections = fetch_pdf_sections(pdf_url)
        if sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


class OpenAlexHTMLSource:
    """OpenAlex의 landing_page_url HTML에서 본문 파싱."""

    name: str = "openalex_html"

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        oa = ref.openalex_oa if ref.openalex_oa is not None else openalex_oa_url(ref.doi)
        if oa is None or not oa.get("is_oa"):
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        ref.openalex_oa = oa
        landing = oa.get("landing_page_url")
        if not landing:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        sections = fetch_html_sections(landing)
        if sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


class UnpaywallSource:
    """Unpaywall에서 OA mirror list 받아 순회. 첫 SUCCESS 반환."""

    name: str = "unpaywall"

    def __init__(self, email: str = "research@scifit-sync.org") -> None:
        self.email = email

    def try_fetch(self, ref: PaperRef) -> FulltextResult:
        locations = unpaywall_oa_locations(ref.doi, email=self.email)
        if not locations:
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
        for loc in locations:
            pdf_url = loc.get("pdf_url")
            if pdf_url:
                sections = fetch_pdf_sections(pdf_url)
                if sections:
                    return FulltextResult(
                        status=FulltextStatus.SUCCESS, sections=sections
                    )
            landing_url = loc.get("landing_url")
            if landing_url:
                sections = fetch_html_sections(landing_url)
                if sections:
                    return FulltextResult(
                        status=FulltextStatus.SUCCESS, sections=sections
                    )
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


def build_default_chain(
    pmc_client,
    europepmc_client,
    unpaywall_email: str = "research@scifit-sync.org",
) -> list[OASource]:
    """기본 OA chain: PMC → EuropePMC → OpenAlex PDF → OpenAlex HTML → Unpaywall.

    새 source 추가는 본 함수 + default_source_names() 두 줄만 수정.
    """
    return [
        PMCSource(pmc_client),
        EuropePMCSource(europepmc_client),
        OpenAlexPDFSource(),
        OpenAlexHTMLSource(),
        UnpaywallSource(email=unpaywall_email),
    ]


def default_source_names() -> list[str]:
    """DEFAULT_CHAIN에 등록된 source name 리스트.

    manifest의 fully-tried 판정 (ACTIVE_SOURCES) 일원화에 사용.
    """
    return ["pmc", "europepmc", "openalex_pdf", "openalex_html", "unpaywall"]
