"""User creation and authentication. No HTTP concerns in here."""

from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, needs_rehash, verify_password
from app.models import Account, Policy, User, Watchlist

DEFAULT_STARTING_CASH = Decimal("100000.0000")


class EmailAlreadyRegistered(Exception):
    pass


async def get_by_email(session: AsyncSession, email: str) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))
    return result.scalar_one_or_none()


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    display_name: str | None = None,
) -> User:
    """Creates the user plus the three rows every account needs to exist:
    a simulated account, a default watchlist, and an initial policy at the
    most conservative autonomy level."""
    if await get_by_email(session, email):
        raise EmailAlreadyRegistered(email)

    user = User(
        email=email.lower(),
        password_hash=hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    await session.flush()

    session.add(
        Account(
            user_id=user.id,
            broker="sim",
            starting_cash=DEFAULT_STARTING_CASH,
            cash=DEFAULT_STARTING_CASH,
            equity=DEFAULT_STARTING_CASH,
        )
    )
    session.add(Watchlist(user_id=user.id, name="My list", is_default=True))
    session.add(Policy(user_id=user.id, version=1, is_active=True))

    await session.flush()
    await session.refresh(user)
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User | None:
    user = await get_by_email(session, email)
    if user is None:
        # Hash anyway so a missing account and a wrong password take the same time.
        hash_password(password)
        return None
    if not user.is_active or not verify_password(password, user.password_hash):
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user
