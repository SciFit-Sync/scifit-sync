"""큐레이션 paper 적재용 공용 helper.

normalize_doi, NCBI ID Converter, OpenAlex DOI lookup, title sanity check.
"""

import logging
import re
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_DOI_URL_PREFIX_RE = re.compile(r"^https?://(dx\.)?doi\.org/", re.IGNORECASE)
_DOI_VALIDATE_RE = re.compile(r"^10\.\d{4,9}/")


def normalize_doi(raw: Optional[str]) -> str:
    """DOI 정규화 — idempotent.

    규칙: strip whitespace → URL prefix 제거 → lowercase → 말미 구두점(.,;) 제거.
    유효하지 않으면 빈 문자열 반환 (10.{prefix}/ 패턴 미충족).
    """
    if not raw or not isinstance(raw, str):
        return ""
    s = raw.strip()
    s = _DOI_URL_PREFIX_RE.sub("", s)
    s = s.lower()
    s = s.rstrip(".,;")
    if not _DOI_VALIDATE_RE.match(s):
        return ""
    return s
