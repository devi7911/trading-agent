import uuid

import jwt
from fastapi import APIRouter, HTTPException, status

from app.api.deps import CurrentUser, SessionDep
from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token, create_refresh_token, decode_token
from app.models import AuditLog
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    TokenPair,
    UserOut,
)
from app.services import users as user_service

router = APIRouter(prefix="/auth", tags=["auth"])
log = get_logger(__name__)


def _tokens(user_id: uuid.UUID) -> TokenPair:
    return TokenPair(
        access_token=create_access_token(str(user_id)),
        refresh_token=create_refresh_token(str(user_id)),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/signup", response_model=TokenPair, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, session: SessionDep) -> TokenPair:
    try:
        user = await user_service.create_user(
            session,
            email=payload.email,
            password=payload.password,
            display_name=payload.display_name,
        )
    except user_service.EmailAlreadyRegistered as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="That email is already registered.",
        ) from exc

    session.add(
        AuditLog(actor_type="user", actor_id=user.id, action="user.signup", entity_type="user",
                 entity_id=user.id, payload={"email": user.email})
    )
    log.info("user_signup", user_id=str(user.id))
    return _tokens(user.id)


@router.post("/login", response_model=TokenPair)
async def login(payload: LoginRequest, session: SessionDep) -> TokenPair:
    user = await user_service.authenticate(
        session, email=payload.email, password=payload.password
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Email or password is incorrect.",
        )
    log.info("user_login", user_id=str(user.id))
    return _tokens(user.id)


@router.post("/refresh", response_model=TokenPair)
async def refresh(payload: RefreshRequest, session: SessionDep) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
        user_id = uuid.UUID(claims["sub"])
    except (jwt.PyJWTError, KeyError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid or expired.",
        ) from exc

    user = await session.get(user_service.User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user.")
    return _tokens(user.id)


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser) -> UserOut:
    return UserOut.model_validate(current_user)
