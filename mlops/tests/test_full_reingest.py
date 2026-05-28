"""full_reingest orchestrator 단위 테스트 (Stage 3.5 게이트 + Stage 4 retry)."""

import gzip
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import requests
from mlops.scripts.full_reingest import stage3_5_validate, stage4_upsert


def _make_ok_jsonl(n=60) -> Path:
    """모든 임계 충족하는 jsonl."""
    weights = [0.3, 0.4, 0.5, 0.6, 0.75, 0.9, 1.0]
    types_list = [
        ["Case Reports"],
        ["Review"],
        ["Journal Article"],
        ["Cohort Study"],
        ["Clinical Trial"],
        ["Randomized Controlled Trial"],
        ["Meta-Analysis"],
    ]
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    records = []
    for p in range(3):
        for c in range(25):
            i = p * 25 + c
            records.append(
                {
                    "chunk_index": c,
                    "paper_pmid": f"pmid{p}",
                    "paper_title": "T",
                    "section_name": "Methods",
                    # local_pdf 서브셋은 PDF_AVG_TOKEN 범위(150~250) 안으로,
                    # 그 외는 AVG_TOKEN 범위(300~450) 만족하도록 분기
                    "token_count": 200 if p == 0 else 400,
                    "search_categories": [],
                    "paper_doi": f"10.1/{p}",
                    "publication_types": types_list[i % len(types_list)],
                    "evidence_weight": weights[i % len(weights)],
                    "fulltext_source": "local_pdf" if p == 0 else "pmc",
                    "published_year": 2018,
                    "embedding": [0.1] * 1024,
                }
            )
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    return tmp


def test_stage3_5_passes_on_good_jsonl():
    path = _make_ok_jsonl(60)
    assert stage3_5_validate(path) is True


def test_stage3_5_fails_on_bad_jsonl():
    path = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(path, "wt", encoding="utf-8") as f:
        f.write(json.dumps({"chunk_index": 0}) + "\n")  # 키 통째 누락
    assert stage3_5_validate(path) is False


# --------------------------------------------------------------------------- #
# Stage 4 retry — load_embeddings.load_api와 동일 패턴(502/503/504 + ConnectionError
# + exponential backoff) 이식 검증. 2,500만 청크 × 1,250~2,100 _post 호출 중
# transient 5xx 1회로 stage4 abort + 수동 재실행 비용을 차단.
# --------------------------------------------------------------------------- #


def _make_minimal_jsonl(n: int = 1) -> Path:
    """retry 테스트용 최소 jsonl (validation 게이트는 거치지 않음)."""
    tmp = Path(tempfile.mkstemp(suffix=".jsonl.gz")[1])
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        for i in range(n):
            r = {
                "chunk_index": i,
                "paper_pmid": "pmid1",
                "paper_title": "T",
                "section_name": "Methods",
                "token_count": 300,
                "search_categories": [],
                "paper_doi": "10.1/x",
                "publication_types": ["Review"],
                "evidence_weight": 0.5,
                "fulltext_source": "pmc",
                "published_year": 2020,
                "content": "abc",
                "embedding": [0.1] * 1024,
            }
            f.write(json.dumps(r) + "\n")
    return tmp


def _fake_resp(status: int, body=None):
    """resp.raise_for_status / resp.json 흉내내는 MagicMock factory."""
    m = MagicMock()
    m.status_code = status
    if status >= 400:
        err = requests.exceptions.HTTPError(response=m)
        m.raise_for_status.side_effect = err
    else:
        m.raise_for_status.return_value = None
        m.json.return_value = body or {"data": {"upserted": 1}}
    return m


def _patch_env(monkeypatch):
    """ADMIN_API_TOKEN / API_BASE_URL 둘 다 stage4_upsert 함수 내부 import 대상에 패치.

    함수가 `from mlops.pipeline.config import ADMIN_API_TOKEN, API_BASE_URL`을
    호출 시점에 수행하므로 모듈 attr를 교체한다.
    """
    monkeypatch.setattr("mlops.pipeline.config.API_BASE_URL", "http://stub")
    monkeypatch.setattr("mlops.pipeline.config.ADMIN_API_TOKEN", "stub-tok")
    # backoff sleep 가속 — 실제 sleep 회피
    monkeypatch.setattr("time.sleep", lambda *a, **kw: None)


def test_stage4_upsert_retries_on_5xx(monkeypatch):
    """502 → 200 시퀀스에서 retry 후 성공."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            return _fake_resp(502)
        return _fake_resp(200, {"data": {"upserted": 1}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2")
    assert total == 1
    assert calls["n"] == 2  # 1차 502 + 2차 성공


def test_stage4_upsert_retries_on_connection_error(monkeypatch):
    """ConnectionError → 200 시퀀스에서도 retry."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise requests.exceptions.ConnectionError("transient")
        return _fake_resp(200, {"data": {"upserted": 1}})

    monkeypatch.setattr("requests.post", fake_post)
    total = stage4_upsert(path, "papers_v2")
    assert total == 1
    assert calls["n"] == 2


def test_stage4_upsert_raises_after_max_retries(monkeypatch):
    """5번 연속 502 → max_retries(5) 초과로 HTTPError raise."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(502)

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(requests.exceptions.HTTPError):
        stage4_upsert(path, "papers_v2")
    assert calls["n"] == 5  # 정확히 max_retries 만큼 호출


def test_stage4_upsert_does_not_retry_on_4xx(monkeypatch):
    """400/401/404 등 4xx는 retry 없이 즉시 raise — 운영자 개입 신호 보존."""
    path = _make_minimal_jsonl(1)
    _patch_env(monkeypatch)

    calls = {"n": 0}

    def fake_post(url, json=None, headers=None, timeout=None):
        calls["n"] += 1
        return _fake_resp(401)

    monkeypatch.setattr("requests.post", fake_post)
    with pytest.raises(requests.exceptions.HTTPError):
        stage4_upsert(path, "papers_v2")
    assert calls["n"] == 1  # 4xx는 1회로 끝
