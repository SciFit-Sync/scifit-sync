"""PMC fulltext 어댑터.

NCBI eutils efetch.fcgi (db=pmc)로 PMC XML을 가져와 PaperSection으로 파싱.
JATS schema는 Europe PMC와 동일하므로 parse_sections를 재사용한다.

cascading orchestrator(fulltext.py)가 첫 번째로 호출하는 어댑터.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests
from mlops.pipeline.europepmc import (
    _RETRYABLE_EXCEPTIONS,
    FulltextResult,
    FulltextStatus,
    parse_sections,
)

logger = logging.getLogger(__name__)


@dataclass
class PMCClient:
    base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    api_key: str = ""
    rate_limit: float = 0.34  # NCBI: 키 있으면 10 req/s, 없으면 3 req/s
    max_retries: int = 3

    def fetch(self, pmcid: str) -> FulltextResult:
        # PMCID 정규화 ("PMC6520849" → "6520849")
        pid = pmcid.replace("PMC", "").strip()

        url = f"{self.base_url}/efetch.fcgi"
        params: dict = {"db": "pmc", "id": pid, "retmode": "xml"}
        if self.api_key:
            params["api_key"] = self.api_key

        last_err: str | None = None
        for attempt in range(self.max_retries):
            if attempt == 0:
                time.sleep(self.rate_limit)
            else:
                backoff = min(60.0, self.rate_limit * (2**attempt))
                logger.warning(
                    "PMC 재시도 %d/%d (%.1fs 백오프): %s",
                    attempt + 1,
                    self.max_retries,
                    backoff,
                    last_err,
                )
                time.sleep(backoff)

            try:
                resp = requests.get(url, params=params, timeout=30)
                resp.raise_for_status()
                sections = parse_sections(resp.content)
                if not sections:
                    return FulltextResult(status=FulltextStatus.NOT_AVAILABLE)
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
