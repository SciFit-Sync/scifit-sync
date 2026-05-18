"""Retry-friendly v2 manifest 모듈.

PubMed PMID 집합으로만 dedup하던 v1 schema 대신, paper별로
fulltext_source와 tried_sources를 보존하여 Phase 2/3 도입 시
"이전에 본문 확보 실패한 paper"를 새 소스로 자동 retry 가능하게 한다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

MANIFEST_SCHEMA_VERSION = 2


@dataclass
class ManifestEntry:
    pmid: str | None
    pmcid: str | None
    openalex_id: str | None
    fulltext_source: str | None
    tried_sources: list[str]
    indexed_at: str | None
    last_tried_at: str

    def to_dict(self) -> dict:
        return {
            "pmid": self.pmid,
            "pmcid": self.pmcid,
            "openalex_id": self.openalex_id,
            "fulltext_source": self.fulltext_source,
            "tried_sources": self.tried_sources,
            "indexed_at": self.indexed_at,
            "last_tried_at": self.last_tried_at,
        }


@dataclass
class Manifest:
    papers: dict[str, ManifestEntry] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> Manifest:
        if not path.exists():
            return cls()

        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError:
            logger.warning("manifest 파싱 실패, 빈 manifest로 시작: %s", path)
            return cls()

        if data.get("version") != MANIFEST_SCHEMA_VERSION:
            logger.info("manifest v1 또는 미지원 schema 감지, clean slate로 시작")
            return cls()

        papers = {
            doi: ManifestEntry(
                pmid=entry.get("pmid"),
                pmcid=entry.get("pmcid"),
                openalex_id=entry.get("openalex_id"),
                fulltext_source=entry.get("fulltext_source"),
                tried_sources=entry.get("tried_sources", []),
                indexed_at=entry.get("indexed_at"),
                last_tried_at=entry["last_tried_at"],
            )
            for doi, entry in data.get("papers", {}).items()
        }
        return cls(papers=papers)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)

        indexed_count = sum(1 for e in self.papers.values() if e.fulltext_source is not None)
        no_fulltext_count = len(self.papers) - indexed_count

        data = {
            "version": MANIFEST_SCHEMA_VERSION,
            "papers": {doi: entry.to_dict() for doi, entry in self.papers.items()},
            "stats": {
                "total_attempted": len(self.papers),
                "indexed_count": indexed_count,
                "no_fulltext_count": no_fulltext_count,
            },
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        logger.info(
            "manifest 저장: %d papers (%d indexed) -> %s",
            len(self.papers),
            indexed_count,
            path,
        )

    def is_indexed(self, doi: str) -> bool:
        entry = self.papers.get(doi)
        return entry is not None and entry.fulltext_source is not None

    def retry_candidates(self, active_sources: set[str]) -> set[str]:
        """active_sources 중 tried_sources에 없는 게 하나라도 있는 paper의 DOI 집합."""
        return {
            doi
            for doi, entry in self.papers.items()
            if entry.fulltext_source is None
            and not set(entry.tried_sources).issuperset(active_sources)
        }

    def record_attempt(
        self,
        *,
        doi: str,
        pmid: str | None,
        pmcid: str | None,
        openalex_id: str | None,
        fulltext_source: str | None,
        tried_sources: Iterable[str],
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.papers.get(doi)
        previous_tried = set(existing.tried_sources) if existing else set()
        merged_tried = sorted(previous_tried.union(tried_sources))

        self.papers[doi] = ManifestEntry(
            pmid=pmid or (existing.pmid if existing else None),
            pmcid=pmcid or (existing.pmcid if existing else None),
            openalex_id=openalex_id or (existing.openalex_id if existing else None),
            fulltext_source=fulltext_source,
            tried_sources=merged_tried,
            indexed_at=now if fulltext_source else (existing.indexed_at if existing else None),
            last_tried_at=now,
        )
