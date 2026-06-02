"""WorkoutX gif 프록시 엔드포인트 + gif_url 정규화 헬퍼 테스트.

- 헬퍼(gif_id_from / to_gif_proxy_url): 다양한 gif_url 형태 → 프록시 URL 변환.
- 프록시(GET /exercises/gif/{id}): 키 없이 호출, fetch_gif_bytes mock으로 200/404 검증.
"""

from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.workoutx import gif_id_from, to_gif_proxy_url


class TestGifHelpers:
    def test_gif_id_from(self):
        assert gif_id_from("/static/gifs/0025.gif") == "0025"  # 과거 죽은 경로
        assert gif_id_from("https://api.workoutxapp.com/v1/gifs/0091.gif") == "0091"  # WorkoutX 직링크
        assert gif_id_from("0102") == "0102"  # 순수 id
        assert gif_id_from("") is None
        assert gif_id_from(None) is None
        assert gif_id_from("https://example.com/bench.gif") is None  # 숫자 id 없음

    def test_to_gif_proxy_url(self):
        base = "https://scifit-sync.com"
        assert to_gif_proxy_url("/static/gifs/0025.gif", base) == "https://scifit-sync.com/api/v1/exercises/gif/0025"
        assert (
            to_gif_proxy_url("https://api.workoutxapp.com/v1/gifs/0091.gif", base)
            == "https://scifit-sync.com/api/v1/exercises/gif/0091"
        )
        assert to_gif_proxy_url(None, base) is None
        assert to_gif_proxy_url("garbage", base) is None
        # base에 trailing slash 있어도 중복 안 됨
        assert to_gif_proxy_url("0025", "https://scifit-sync.com/") == "https://scifit-sync.com/api/v1/exercises/gif/0025"


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


class TestGifProxy:
    @pytest.mark.asyncio
    async def test_returns_gif_without_auth(self, client, monkeypatch):
        # 인증 헤더 없이도 200 (공개 이미지) + Cache-Control
        monkeypatch.setattr(
            "app.api.v1.exercises.fetch_gif_bytes",
            AsyncMock(return_value=(b"GIF89a\x01\x00", "image/gif")),
        )
        resp = await client.get("/api/v1/exercises/gif/0025")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "image/gif"
        assert "max-age" in resp.headers.get("cache-control", "")
        assert resp.content == b"GIF89a\x01\x00"

    @pytest.mark.asyncio
    async def test_404_when_missing(self, client, monkeypatch):
        monkeypatch.setattr(
            "app.api.v1.exercises.fetch_gif_bytes",
            AsyncMock(return_value=None),
        )
        resp = await client.get("/api/v1/exercises/gif/9999")
        assert resp.status_code == 404
