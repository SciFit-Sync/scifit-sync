"""큐레이션 paper 명시 입력 ingest.

Spec §4.2 단일 상태머신 참조.

사용법 (cloud GPU 서버에서):
    python -m mlops.scripts.ingest_curated_pmids \\
        --provenance mlops/data/curated_provenance.json \\
        [--dry-run] [--limit N]
"""

import argparse
import contextlib
import fcntl
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.curated import (
    normalize_doi,
    ncbi_pmid_to_doi,
    openalex_doi_lookup,
    title_keyword_overlap,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-5s [%(name)s] %(message)s")
logger = logging.getLogger(__name__)

LOCK_FILENAME = ".ingest.lock"
TITLE_OVERLAP_THRESHOLD = 0.2


@contextlib.contextmanager
def acquire_lock(lock_path: Path):
    """flock 기반 advisory lock. 실패 시 BlockingIOError."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        except Exception:
            pass
        os.close(fd)
