"""ingest_curated_pmids 단위 테스트."""
import fcntl
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestLockAcquisition:
    def test_acquires_lock_when_free(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock
        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path) as lock_fd:
            assert lock_fd is not None
        # 락 해제 후 파일 존재 OK (lock 파일은 reuse)
        assert lock_path.exists()

    def test_lock_fails_when_held(self, tmp_path):
        from mlops.scripts.ingest_curated_pmids import acquire_lock
        lock_path = tmp_path / ".ingest.lock"
        with acquire_lock(lock_path):
            # 이미 잡힌 락은 두 번째 호출에서 BlockingIOError
            with pytest.raises(BlockingIOError):
                with acquire_lock(lock_path):
                    pass
