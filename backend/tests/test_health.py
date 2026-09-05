"""No database required - these prove the app boots and routes."""


async def test_root(client):
    r = await client.get("/")
    assert r.status_code == 200
    assert r.json()["service"] == "agentic-trading-desk"


async def test_liveness(client):
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["version"]


async def test_correlation_id_is_echoed(client):
    r = await client.get("/api/v1/health/live", headers={"X-Correlation-ID": "abc-123"})
    assert r.headers["X-Correlation-ID"] == "abc-123"


async def test_correlation_id_is_generated(client):
    r = await client.get("/api/v1/health/live")
    assert len(r.headers["X-Correlation-ID"]) == 36


async def test_openapi_is_served(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "/api/v1/auth/login" in r.json()["paths"]
