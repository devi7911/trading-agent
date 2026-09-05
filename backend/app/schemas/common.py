from typing import Literal

from pydantic import BaseModel


class Message(BaseModel):
    detail: str


class HealthStatus(BaseModel):
    status: Literal["ok", "degraded", "down"]
    version: str
    checks: dict[str, str] = {}
