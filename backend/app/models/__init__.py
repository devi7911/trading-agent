"""Import every model here so Alembic autogenerate sees the full metadata."""

from app.models.account import Account
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.instrument import Instrument
from app.models.policy import AutonomyLevel, Policy, RiskProfile
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

__all__ = [
    "Account",
    "AuditLog",
    "AutonomyLevel",
    "Base",
    "Instrument",
    "Policy",
    "RiskProfile",
    "User",
    "Watchlist",
    "WatchlistItem",
]
