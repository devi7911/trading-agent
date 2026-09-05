"""The reasoning layer.

The design rule the whole project rests on: **the model proposes, the rules
decide what it is allowed to propose about, and the gate decides what happens.**

Concretely, the model may only:
  * agree with the rule-based consensus and adjust conviction, or
  * downgrade an action to HOLD.

It may NOT invent a direction the strategies did not produce. A model that
hallucinates a reason to buy cannot act on it, because the rules never offered
buying as an option. This keeps the failure mode "the agent did nothing" rather
than "the agent bought something on the strength of a fabricated news story".

If the model is unavailable, slow, or returns anything that fails validation,
the rule-based decision stands unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from app.core.logging import get_logger
from app.reasoning.llm import Completion, LLMClient, extract_json
from app.reasoning.schema import SCHEMA_HINT, ModelDecision
from app.strategy.signals import Direction, Signal

log = get_logger(__name__)

SYSTEM_PROMPT = """You are a risk-aware analyst reviewing a proposed equity trade.

You are reviewing a decision that quantitative rules have already made. Your job
is to judge whether the supporting context justifies acting on it.

You may agree, or you may downgrade the action to "hold". You may not propose a
different direction: if the rules say buy and you disagree, the answer is hold.

Be sceptical. Most signals are noise. Downgrading is the safe answer and the
common one. Never invent facts that are not in the context you were given."""

# Conviction below this after review is not worth acting on.
REVIEW_FLOOR = 0.2


@dataclass
class Reasoning:
    """The outcome of the review, whichever path produced it."""

    direction: Direction
    conviction: float
    rationale: str
    source: str                       # "rules" | "llm" | "llm_fallback"
    model_used: str | None = None
    duration_ms: int = 0
    key_factors: list[str] = field(default_factory=list)
    fallback_reason: str | None = None

    def to_dict(self) -> dict:
        return {
            "direction": str(self.direction),
            "conviction": round(self.conviction, 4),
            "rationale": self.rationale,
            "source": self.source,
            "model": self.model_used,
            "duration_ms": self.duration_ms,
            "key_factors": self.key_factors,
            "fallback_reason": self.fallback_reason,
        }


def build_prompt(
    *,
    symbol: str,
    name: str,
    sector: str | None,
    proposal: Signal,
    signals: list[Signal],
    price: Decimal,
    held_quantity: int,
    unrealised_pct: float | None,
    headlines: list[dict],
) -> str:
    lines = [
        f"Symbol: {symbol} ({name}) - {sector or 'unclassified'}",
        f"Last price: {price}",
        f"Current position: {held_quantity} shares"
        + (f", unrealised {unrealised_pct:+.1f}%" if unrealised_pct is not None else ""),
        "",
        f"PROPOSED ACTION (from the rules): {proposal.direction.upper()}",
        f"Rule conviction: {proposal.strength:.2f}",
        f"Rule reasoning: {proposal.reason}",
        "",
        "Individual strategy views:",
    ]
    for s in signals:
        lines.append(f"  - {s.strategy}: {s.direction} ({s.strength:.2f}) - {s.reason}")

    if headlines:
        lines += ["", "Recent headlines (most recent first):"]
        for item in headlines[:6]:
            lines.append(
                f"  - [{item['published_at'][:10]}] {item['headline']} "
                f"(sentiment {item['sentiment']:+.2f})"
            )
    else:
        lines += ["", "No recent headlines."]

    lines += [
        "",
        f"Should the agent act on the proposed {proposal.direction.upper()}?",
        "Agree with the direction, or answer \"hold\". Do not propose the opposite.",
        "",
        SCHEMA_HINT,
    ]
    return "\n".join(lines)


def _fallback(proposal: Signal, reason: str) -> Reasoning:
    return Reasoning(
        direction=proposal.direction,
        conviction=proposal.strength,
        rationale=proposal.reason,
        source="llm_fallback",
        fallback_reason=reason,
    )


async def review(
    client: LLMClient,
    *,
    symbol: str,
    name: str,
    sector: str | None,
    proposal: Signal,
    signals: list[Signal],
    price: Decimal,
    held_quantity: int = 0,
    unrealised_pct: float | None = None,
    headlines: list[dict] | None = None,
) -> Reasoning:
    """Ask the model to review a rule-based proposal. Never raises."""
    if proposal.direction is Direction.HOLD:
        return Reasoning(Direction.HOLD, 0.0, proposal.reason, source="rules")

    prompt = build_prompt(
        symbol=symbol, name=name, sector=sector, proposal=proposal, signals=signals,
        price=price, held_quantity=held_quantity, unrealised_pct=unrealised_pct,
        headlines=headlines or [],
    )
    completion: Completion = await client.complete(prompt, system=SYSTEM_PROMPT)
    if not completion.ok:
        return _fallback(proposal, completion.error or "completion failed")

    payload = extract_json(completion.text)
    if payload is None:
        log.info("llm_unparseable", symbol=symbol)
        return _fallback(proposal, "response was not JSON")

    try:
        decision = ModelDecision.model_validate(payload)
    except Exception as exc:
        log.info("llm_schema_violation", symbol=symbol, error=type(exc).__name__)
        return _fallback(proposal, f"schema violation: {type(exc).__name__}")

    # The model may agree or downgrade. It may never flip the direction - that
    # would let a hallucination originate a trade rather than merely permit one.
    if decision.direction is not proposal.direction:
        if decision.direction is Direction.HOLD:
            return Reasoning(
                Direction.HOLD, 0.0,
                f"Reviewed and held: {decision.rationale}",
                source="llm", model_used=completion.model,
                duration_ms=completion.duration_ms, key_factors=decision.key_factors,
            )
        log.info("llm_direction_override_refused", symbol=symbol,
                 proposed=str(proposal.direction), returned=str(decision.direction))
        return _fallback(proposal, "model tried to change the direction")

    # Agreement. Conviction is the lower of the two: the model can temper the
    # rules but never make them bolder than they were.
    conviction = min(proposal.strength, decision.conviction)
    if conviction < REVIEW_FLOOR:
        return Reasoning(
            Direction.HOLD, 0.0,
            f"Conviction fell to {conviction:.2f} after review: {decision.rationale}",
            source="llm", model_used=completion.model,
            duration_ms=completion.duration_ms, key_factors=decision.key_factors,
        )

    return Reasoning(
        direction=proposal.direction,
        conviction=conviction,
        rationale=decision.rationale,
        source="llm",
        model_used=completion.model,
        duration_ms=completion.duration_ms,
        key_factors=decision.key_factors,
    )


__all__ = ["REVIEW_FLOOR", "Reasoning", "build_prompt", "review"]
