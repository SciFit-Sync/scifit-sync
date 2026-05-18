"""Europe PMC fulltext 어댑터.

PMID 또는 DOI를 입력 받아 fulltext XML을 가져오고 PaperSection 리스트로 파싱한다.
PMC와 매우 유사한 JATS XML 형식.

Cascading fallback에서 PMC 다음 자리. 결과는 FulltextResult로 success / not_available /
transient_error 중 하나로 분류된다.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum

import requests
from defusedxml import ElementTree as ET
from mlops.pipeline.models import PaperSection

logger = logging.getLogger(__name__)


class FulltextStatus(str, Enum):
    SUCCESS = "success"
    NOT_AVAILABLE = "not_available"
    TRANSIENT_ERROR = "transient_error"


@dataclass
class FulltextResult:
    status: FulltextStatus
    sections: list[PaperSection] = field(default_factory=list)
    error: str | None = None


_RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ChunkedEncodingError,
    requests.exceptions.ConnectionError,
    requests.exceptions.Timeout,
)


def _get_text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_sections(xml_bytes: bytes) -> list[PaperSection]:
    """Europe PMC fulltext XML에서 <body><sec> 요소를 추출한다."""
    root = ET.fromstring(xml_bytes)
    body = root.find(".//body")
    if body is None:
        return []

    sections: list[PaperSection] = []
    for sec in body.findall(".//sec"):
        title_el = sec.find("title")
        name = _get_text(title_el) or "Untitled"

        paragraphs = [_get_text(p) for p in sec.findall("p") if _get_text(p)]
        content = "\n".join(paragraphs).strip()
        if content:
            sections.append(PaperSection(name=name, content=content))

    return sections


@dataclass
class EuropePMCClient:
    base_url: str
    rate_limit: float = 1.0
    max_retries: int = 3

    def _fetch(self, url: str) -> FulltextResult:
        last_err: str | None = None
        for attempt in range(self.max_retries):
            if attempt == 0:
                time.sleep(self.rate_limit)
            else:
                backoff = min(60.0, self.rate_limit * (2**attempt))
                logger.warning(
                    "EuropePMC 재시도 %d/%d (%.1fs 백오프): %s",
                    attempt + 1,
                    self.max_retries,
                    backoff,
                    last_err,
                )
                time.sleep(backoff)

            try:
                resp = requests.get(url, timeout=30)
                resp.raise_for_status()
                sections = parse_sections(resp.content)
                return FulltextResult(status=FulltextStatus.SUCCESS, sections=sections)
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status == 404:
                    return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
                if status is not None and (status == 429 or 500 <= status < 600):
                    last_err = f"HTTP {status}"
                    continue
                return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=str(e))
            except _RETRYABLE_EXCEPTIONS as e:
                last_err = str(e)
                continue

        return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=last_err)

    def fetch_by_pmid(self, pmid: str) -> FulltextResult:
        """PMID로 fulltext 조회."""
        url = f"{self.base_url}/MED/{pmid}/fullTextXML"
        return self._fetch(url)

    def fetch_by_doi(self, doi: str) -> FulltextResult:
        """DOI로 fulltext 조회.

        먼저 Europe PMC search API로 source+id를 찾은 뒤 fulltext 어댑터 호출.
        search/fulltext 두 단계 모두 동일한 retry 정책 적용.
        """
        search_url = f"{self.base_url}/search?query=DOI:{doi}&resultType=core&format=json"

        last_err: str | None = None
        for attempt in range(self.max_retries):
            if attempt == 0:
                time.sleep(self.rate_limit)
            else:
                backoff = min(60.0, self.rate_limit * (2**attempt))
                logger.warning(
                    "EuropePMC search 재시도 %d/%d (%.1fs 백오프): %s",
                    attempt + 1,
                    self.max_retries,
                    backoff,
                    last_err,
                )
                time.sleep(backoff)

            try:
                resp = requests.get(search_url, timeout=30)
                resp.raise_for_status()
                data = resp.json()
            except requests.exceptions.HTTPError as e:
                status = getattr(e.response, "status_code", None)
                if status == 404:
                    return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
                if status is not None and (status == 429 or 500 <= status < 600):
                    last_err = f"HTTP {status}"
                    continue
                return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=str(e))
            except _RETRYABLE_EXCEPTIONS as e:
                last_err = str(e)
                continue
            except requests.exceptions.RequestException as e:
                return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=str(e))

            results = data.get("resultList", {}).get("result", [])
            if not results:
                return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)

            first = results[0]
            source = first.get("source")
            pmid = first.get("pmid")
            ext_id = first.get("id")

            if source == "MED" and pmid:
                return self.fetch_by_pmid(pmid)
            if source and ext_id:
                url = f"{self.base_url}/{source}/{ext_id}/fullTextXML"
                return self._fetch(url)
            return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)

        return FulltextResult(status=FulltextStatus.TRANSIENT_ERROR, error=last_err)
