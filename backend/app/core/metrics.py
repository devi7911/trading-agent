"""Prometheus metrics.

Deliberately small. The metric that matters most is agent staleness: everything
else can look healthy while the agent has quietly stopped ticking, and that is
the failure you find out about a week later.
"""

from __future__ import annotations

import time

_REGISTRY: dict[str, float] = {}
_COUNTERS: dict[str, float] = {}
_LABELS: dict[str, dict[str, str]] = {}


def counter(name: str, value: float = 1.0, **labels: str) -> None:
    key = _key(name, labels)
    _COUNTERS[key] = _COUNTERS.get(key, 0.0) + value
    _LABELS[key] = labels


def gauge(name: str, value: float, **labels: str) -> None:
    key = _key(name, labels)
    _REGISTRY[key] = value
    _LABELS[key] = labels


def _key(name: str, labels: dict[str, str]) -> str:
    if not labels:
        return name
    rendered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{rendered}}}"


def render() -> str:
    """Prometheus text exposition format."""
    lines = ["# Agentic Trading Desk metrics"]
    for key, value in sorted(_COUNTERS.items()):
        lines.append(f"{key} {value}")
    for key, value in sorted(_REGISTRY.items()):
        lines.append(f"{key} {value}")
    lines.append(f"process_uptime_seconds {time.time() - _STARTED}")
    return "\n".join(lines) + "\n"


def reset() -> None:
    """Tests only."""
    _REGISTRY.clear()
    _COUNTERS.clear()
    _LABELS.clear()


_STARTED = time.time()

__all__ = ["counter", "gauge", "render", "reset"]
