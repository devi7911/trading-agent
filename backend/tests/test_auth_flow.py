"""End-to-end signup/login. Needs Postgres, so it runs inside compose:

    docker compose exec api pytest
"""

import uuid

import pytest


@pytest.fixture
def credentials() -> dict[str, str]:
    return {
        "email": f"devi+{uuid.uuid4().hex[:8]}@example.com",
        "password": "a-sufficiently-long-password",
        "display_name": "Devi",
    }


@pytest.mark.integration
async def test_signup_then_me(client, credentials):
    r = await client.post("/api/v1/auth/signup", json=credentials)
    assert r.status_code == 201, r.text
    tokens = r.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert me.status_code == 200
    assert me.json()["email"] == credentials["email"]


@pytest.mark.integration
async def test_duplicate_email_is_rejected(client, credentials):
    assert (await client.post("/api/v1/auth/signup", json=credentials)).status_code == 201
    second = await client.post("/api/v1/auth/signup", json=credentials)
    assert second.status_code == 409


@pytest.mark.integration
async def test_login_with_wrong_password_fails(client, credentials):
    await client.post("/api/v1/auth/signup", json=credentials)
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": credentials["email"], "password": "definitely-not-it"},
    )
    assert r.status_code == 401


async def test_me_requires_a_token(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
