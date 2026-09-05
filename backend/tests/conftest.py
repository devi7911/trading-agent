import os

os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-real-use")
os.environ.setdefault("APP_ENV", "test")

from collections.abc import AsyncGenerator

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    from app.main import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
