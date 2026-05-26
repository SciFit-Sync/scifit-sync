"""monthly_ingest.py 핵심 함수 단위 테스트 — 서버 dedup fallback 시나리오 중심."""

import sys
from pathlib import Path
from types import SimpleNamespace

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from mlops.pipeline.oa_fetcher import default_source_names
from mlops.scripts import monthly_ingest


def test_active_sources_matches_default_chain():
    """ACTIVE_SOURCES가 default_source_names()와 일치하는지 검증 (단일 정의 보장)."""
    assert set(default_source_names()) == monthly_ingest.ACTIVE_SOURCES


def test_fetch_dois_returns_empty_when_env_missing(monkeypatch):
    """API_BASE_URL/ADMIN_API_TOKEN 미설정 시 빈 set — manifest 단독 fallback."""
    monkeypatch.setattr(monthly_ingest, "API_BASE_URL", None)
    monkeypatch.setattr(monthly_ingest, "ADMIN_API_TOKEN", None)
    assert monthly_ingest._fetch_indexed_dois_from_server() == set()


def test_fetch_dois_returns_set_on_success(monkeypatch):
    """정상 응답 — `data.dois`를 set으로 반환."""
    monkeypatch.setattr(monthly_ingest, "API_BASE_URL", "http://x")
    monkeypatch.setattr(monthly_ingest, "ADMIN_API_TOKEN", "t")

    fake_resp = SimpleNamespace(
        json=lambda: {"success": True, "data": {"dois": ["10.1/a", "10.1/b"], "count": 2}},
        raise_for_status=lambda: None,
    )
    monkeypatch.setattr(monthly_ingest.requests, "get", lambda *_args, **_kwargs: fake_resp)
    assert monthly_ingest._fetch_indexed_dois_from_server() == {"10.1/a", "10.1/b"}


def test_fetch_dois_returns_empty_on_request_exception(monkeypatch):
    """네트워크/HTTP 실패 → 빈 set fallback (manifest 단독 흐름으로 회귀)."""
    monkeypatch.setattr(monthly_ingest, "API_BASE_URL", "http://x")
    monkeypatch.setattr(monthly_ingest, "ADMIN_API_TOKEN", "t")

    def raise_request(*_args, **_kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(monthly_ingest.requests, "get", raise_request)
    assert monthly_ingest._fetch_indexed_dois_from_server() == set()


def test_fetch_dois_returns_empty_on_malformed_payload(monkeypatch):
    """응답 envelope이 깨졌으면(KeyError) 빈 set."""
    monkeypatch.setattr(monthly_ingest, "API_BASE_URL", "http://x")
    monkeypatch.setattr(monthly_ingest, "ADMIN_API_TOKEN", "t")

    fake_resp = SimpleNamespace(json=lambda: {"unexpected": True}, raise_for_status=lambda: None)
    monkeypatch.setattr(monthly_ingest.requests, "get", lambda *_args, **_kwargs: fake_resp)
    assert monthly_ingest._fetch_indexed_dois_from_server() == set()


def test_fetch_dois_returns_empty_on_json_decode_error(monkeypatch):
    """resp.json()이 ValueError(JSONDecodeError) 던지면 빈 set."""
    monkeypatch.setattr(monthly_ingest, "API_BASE_URL", "http://x")
    monkeypatch.setattr(monthly_ingest, "ADMIN_API_TOKEN", "t")

    def bad_json():
        raise ValueError("invalid JSON")

    fake_resp = SimpleNamespace(json=bad_json, raise_for_status=lambda: None)
    monkeypatch.setattr(monthly_ingest.requests, "get", lambda *_args, **_kwargs: fake_resp)
    assert monthly_ingest._fetch_indexed_dois_from_server() == set()
