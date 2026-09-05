"""Password hashing and token handling. Pure unit tests."""

import uuid

import jwt
import pytest

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_is_argon2id_and_salted():
    h1 = hash_password("correct horse battery staple")
    h2 = hash_password("correct horse battery staple")
    assert h1.startswith("$argon2id$")
    assert h1 != h2, "same password must not produce the same hash"


def test_verify_round_trip():
    h = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong password entirely", h)


def test_verify_rejects_garbage_hash_without_raising():
    assert verify_password("anything", "not-a-hash") is False


def test_access_token_round_trip():
    uid = str(uuid.uuid4())
    claims = decode_token(create_access_token(uid), expected_type="access")
    assert claims["sub"] == uid
    assert claims["typ"] == "access"
    assert claims["jti"]


def test_refresh_token_cannot_be_used_as_access_token():
    token = create_refresh_token(str(uuid.uuid4()))
    with pytest.raises(jwt.InvalidTokenError):
        decode_token(token, expected_type="access")


def test_tampered_token_is_rejected():
    token = create_access_token(str(uuid.uuid4()))
    tampered = token[:-3] + ("aaa" if not token.endswith("aaa") else "bbb")
    with pytest.raises(jwt.PyJWTError):
        decode_token(tampered)
