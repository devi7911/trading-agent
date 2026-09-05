"""The reasoning layer.

A language model's output is untrusted input. These tests pin the boundary:
what it is allowed to change, what it is not, and that every failure mode leaves
the rule-based decision standing rather than blocking the agent.
"""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.reasoning.llm import Completion, LLMClient, extract_json
from app.reasoning.reasoner import REVIEW_FLOOR, build_prompt, review
from app.reasoning.schema import ModelDecision
from app.strategy.signals import Direction, Signal

BUY = Signal("TEST", Direction.BUY, 0.8, "momentum", "strong trend")
SELL = Signal("TEST", Direction.SELL, 0.7, "momentum", "breaking down")
HOLD = Signal("TEST", Direction.HOLD, 0.0, "consensus", "no edge")


class FakeClient(LLMClient):
    """Stands in for Ollama so the boundary can be tested without a model."""

    def __init__(self, response: str = "", ok: bool = True, error: str | None = None):
        super().__init__(base_url="http://fake", model="fake-model")
        self._response = response
        self._ok = ok
        self._error = error

    async def available(self) -> bool:
        return self._ok

    async def complete(self, prompt: str, *, system: str = "", temperature: float = 0.1):
        return Completion(ok=self._ok, text=self._response, error=self._error,
                          model=self.model)


async def _review(client: LLMClient, proposal: Signal = BUY):
    return await review(
        client, symbol="TEST", name="Test Corp", sector="Technology",
        proposal=proposal, signals=[proposal], price=Decimal("100"),
    )


# --- JSON salvage ------------------------------------------------------------

def test_plain_json_parses():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_fenced_json_parses():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_json_with_commentary_around_it_parses():
    assert extract_json('Here you go:\n{"a": 1}\nHope that helps!') == {"a": 1}


def test_nested_objects_survive_the_brace_matching():
    assert extract_json('{"a": {"b": 2}, "c": 3}') == {"a": {"b": 2}, "c": 3}


@pytest.mark.parametrize("text", ["", "no json here", "{broken", "[1, 2, 3]", "{"])
def test_unsalvageable_output_returns_none(text):
    assert extract_json(text) is None


# --- the schema --------------------------------------------------------------

def test_a_valid_decision_parses():
    d = ModelDecision.model_validate(
        {"direction": "buy", "conviction": 0.6, "rationale": "looks fine"}
    )
    assert d.direction is Direction.BUY


@pytest.mark.parametrize("conviction", [-0.1, 1.1, 5])
def test_conviction_outside_the_unit_interval_is_rejected(conviction):
    with pytest.raises(ValidationError):
        ModelDecision.model_validate(
            {"direction": "buy", "conviction": conviction, "rationale": "x"}
        )


def test_an_invented_direction_is_rejected():
    with pytest.raises(ValidationError):
        ModelDecision.model_validate(
            {"direction": "yolo", "conviction": 0.5, "rationale": "x"}
        )


def test_an_overlong_rationale_is_truncated_not_rejected():
    d = ModelDecision.model_validate(
        {"direction": "hold", "conviction": 0.0, "rationale": "x" * 900}
    )
    assert len(d.rationale) <= 400


def test_key_factors_are_capped():
    d = ModelDecision.model_validate({
        "direction": "buy", "conviction": 0.5, "rationale": "x",
        "key_factors": [f"factor {i}" for i in range(20)],
    })
    assert len(d.key_factors) <= 5


# --- what the reviewer may and may not do ------------------------------------

async def test_agreement_is_accepted():
    client = FakeClient('{"direction":"buy","conviction":0.7,"rationale":"agreed"}')
    outcome = await _review(client)
    assert outcome.direction is Direction.BUY
    assert outcome.source == "llm"
    assert outcome.rationale == "agreed"


async def test_conviction_is_capped_by_the_rules():
    """The model may temper the rules. It may never make them bolder."""
    client = FakeClient('{"direction":"buy","conviction":1.0,"rationale":"very sure"}')
    outcome = await _review(client, Signal("TEST", Direction.BUY, 0.4, "m", "modest"))
    assert outcome.conviction == pytest.approx(0.4)


async def test_a_downgrade_to_hold_is_honoured():
    client = FakeClient('{"direction":"hold","conviction":0.0,"rationale":"too thin"}')
    outcome = await _review(client)
    assert outcome.direction is Direction.HOLD
    assert "Reviewed and held" in outcome.rationale


async def test_the_model_cannot_flip_the_direction():
    """The critical boundary: a hallucination must not be able to originate a
    trade the strategies never proposed."""
    client = FakeClient('{"direction":"sell","conviction":0.9,"rationale":"actually short it"}')
    outcome = await _review(client, BUY)
    assert outcome.direction is Direction.BUY, "the model changed the direction"
    assert outcome.source == "llm_fallback"
    assert "direction" in (outcome.fallback_reason or "")


async def test_the_model_cannot_flip_a_sell_into_a_buy():
    client = FakeClient('{"direction":"buy","conviction":0.9,"rationale":"reversal"}')
    outcome = await _review(client, SELL)
    assert outcome.direction is Direction.SELL
    assert outcome.source == "llm_fallback"


async def test_conviction_below_the_floor_becomes_a_hold():
    client = FakeClient(
        '{"direction":"buy","conviction":%s,"rationale":"marginal"}' % (REVIEW_FLOOR / 2)
    )
    outcome = await _review(client)
    assert outcome.direction is Direction.HOLD


# --- every failure mode falls back rather than blocking ----------------------

async def test_a_dead_server_falls_back_to_the_rules():
    client = FakeClient(ok=False, error="ConnectError")
    outcome = await _review(client)
    assert outcome.direction is BUY.direction
    assert outcome.conviction == BUY.strength
    assert outcome.source == "llm_fallback"


async def test_unparseable_output_falls_back():
    outcome = await _review(FakeClient("I think you should buy!"))
    assert outcome.source == "llm_fallback"
    assert outcome.fallback_reason == "response was not JSON"


async def test_a_schema_violation_falls_back():
    outcome = await _review(FakeClient('{"direction":"buy","conviction":42}'))
    assert outcome.source == "llm_fallback"
    assert "schema" in (outcome.fallback_reason or "")


async def test_an_empty_response_falls_back():
    outcome = await _review(FakeClient(""))
    assert outcome.source == "llm_fallback"


async def test_a_hold_proposal_is_never_sent_for_review():
    """No point spending seconds of inference to confirm doing nothing."""
    outcome = await _review(FakeClient('{"direction":"buy","conviction":1.0,"rationale":"x"}'),
                            HOLD)
    assert outcome.source == "rules"
    assert outcome.direction is Direction.HOLD


# --- the prompt --------------------------------------------------------------

def test_the_prompt_carries_the_proposal_and_the_evidence():
    prompt = build_prompt(
        symbol="TEST", name="Test Corp", sector="Technology", proposal=BUY,
        signals=[BUY], price=Decimal("100"), held_quantity=10, unrealised_pct=5.0,
        headlines=[{"published_at": "2026-01-01T00:00:00", "headline": "Big news",
                    "sentiment": 0.5}],
    )
    assert "PROPOSED ACTION" in prompt
    assert "Big news" in prompt
    assert "Do not propose the opposite" in prompt
    assert "10 shares" in prompt


def test_the_prompt_says_so_when_there_is_no_news():
    prompt = build_prompt(
        symbol="TEST", name="Test Corp", sector=None, proposal=BUY, signals=[BUY],
        price=Decimal("100"), held_quantity=0, unrealised_pct=None, headlines=[],
    )
    assert "No recent headlines" in prompt
