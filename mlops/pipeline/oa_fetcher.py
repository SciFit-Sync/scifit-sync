"""Unified OA fetcher chain.

Chain-of-Resolvers 패턴으로 다양한 OA source를 순회한다.
새 source 추가는 OASource Protocol 구현 + DEFAULT_CHAIN 등록 두 단계.

Spec: docs/superpowers/specs/2026-05-24-oa-fetcher-chain-design.md
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

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
        if result.had_transient_error:
            return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR)
        if result.sections:
            return FulltextResult(status=FulltextStatus.SUCCESS, sections=result.sections)
        return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)


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
