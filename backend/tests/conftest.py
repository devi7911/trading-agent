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


@pytest.fixture(autouse=True)
async def _dispose_engine():
    """The engine is module-level and its pool binds to whichever event loop
    first used it. pytest-asyncio gives each test a fresh loop, so a pooled
    connection from the previous test raises 'Event loop is closed'.
    Disposing after every test keeps each one on its own clean pool."""
    yield
    from app.core.db import engine

    await engine.dispose()
