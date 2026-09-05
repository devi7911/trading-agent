"""The contract the model must satisfy.

A language model's output is untrusted input. It is parsed into this schema
before anything downstream sees it, and anything that fails to parse is
discarded in favour of the rule-based decision. The model cannot invent a field,
exceed a bound, or return prose where a number belongs.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.strategy.signals import Direction

MAX_RATIONALE = 400
MAX_KEY_FACTORS = 5


class ModelDecision(BaseModel):
    """What the model is allowed to say. Nothing else is accepted."""

    direction: Direction
    conviction: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)
    key_factors: list[str] = Field(default_factory=list)

    # Length is TRIMMED, not enforced. A max_length constraint rejects the whole
    # decision when the model is merely verbose - which they routinely are - and
    # throws away an otherwise valid answer. Be liberal in what is accepted,
    # strict about what is acted on: bounds that matter (direction, conviction)
    # are enforced above; bounds that are cosmetic are trimmed here.
    @field_validator("rationale")
    @classmethod
    def trim_rationale(cls, value: str) -> str:
        return value.strip()[:MAX_RATIONALE]

    @field_validator("key_factors")
    @classmethod
    def trim_factors(cls, values: list[str]) -> list[str]:
        return [v.strip()[:120] for v in values if v and v.strip()][:MAX_KEY_FACTORS]


SCHEMA_HINT = """Respond with JSON only, matching exactly this shape:
{
  "direction": "buy" | "sell" | "hold",
  "conviction": 0.0 to 1.0,
  "rationale": "one or two sentences",
  "key_factors": ["short phrase", "short phrase"]
}
No prose outside the JSON. No markdown fences."""


__all__ = ["MAX_KEY_FACTORS", "MAX_RATIONALE", "SCHEMA_HINT", "ModelDecision"]
