import os

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

os.environ["RATE_LIMIT_ENABLED"] = "false"
os.environ.setdefault("ADMIN_API_TOKEN", "test-admin-token")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()

from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
