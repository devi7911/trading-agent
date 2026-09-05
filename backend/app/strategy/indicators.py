"""Technical indicators over a price series.

Pure numpy, pure functions, no I/O. Every one returns an array the same length
as its input, with the warm-up region filled with NaN rather than a fabricated
value - a strategy must not be able to trade on an indicator that has not yet
seen enough history.
"""

from __future__ import annotations

import numpy as np


def _validate(values: np.ndarray, period: int) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    if arr.ndim != 1:
        raise ValueError("expected a one-dimensional series")
    if period < 1:
        raise ValueError("period must be at least 1")
    return arr


def sma(values: np.ndarray, period: int) -> np.ndarray:
    arr = _validate(values, period)
    out = np.full(arr.shape, np.nan)
    if len(arr) < period:
        return out
    cumulative = np.cumsum(np.insert(arr, 0, 0.0))
    out[period - 1 :] = (cumulative[period:] - cumulative[:-period]) / period
    return out


def ema(values: np.ndarray, period: int) -> np.ndarray:
    arr = _validate(values, period)
    out = np.full(arr.shape, np.nan)
    if len(arr) < period:
        return out
    alpha = 2.0 / (period + 1)
    out[period - 1] = arr[:period].mean()
    for i in range(period, len(arr)):
        out[i] = alpha * arr[i] + (1 - alpha) * out[i - 1]
    return out


def rsi(values: np.ndarray, period: int = 14) -> np.ndarray:
    """Wilder's RSI. Bounded [0, 100]."""
    arr = _validate(values, period)
    out = np.full(arr.shape, np.nan)
    if len(arr) <= period:
        return out

    delta = np.diff(arr)
    gain = np.where(delta > 0, delta, 0.0)
    loss = np.where(delta < 0, -delta, 0.0)

    avg_gain = gain[:period].mean()
    avg_loss = loss[:period].mean()
    out[period] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)

    for i in range(period + 1, len(arr)):
        avg_gain = (avg_gain * (period - 1) + gain[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + loss[i - 1]) / period
        out[i] = 100.0 if avg_loss == 0 else 100 - 100 / (1 + avg_gain / avg_loss)
    return out


def macd(
    values: np.ndarray, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (macd line, signal line, histogram)."""
    arr = _validate(values, slow)
    line = ema(arr, fast) - ema(arr, slow)
    valid = ~np.isnan(line)
    signal_line = np.full(arr.shape, np.nan)
    if valid.any():
        first = int(np.argmax(valid))
        signal_line[first:] = ema(line[first:], signal)
    return line, signal_line, line - signal_line


def bollinger(
    values: np.ndarray, period: int = 20, deviations: float = 2.0
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Returns (upper, middle, lower)."""
    arr = _validate(values, period)
    middle = sma(arr, period)
    std = np.full(arr.shape, np.nan)
    for i in range(period - 1, len(arr)):
        std[i] = arr[i - period + 1 : i + 1].std()
    return middle + deviations * std, middle, middle - deviations * std


def true_range(high: np.ndarray, low: np.ndarray, close: np.ndarray) -> np.ndarray:
    high, low, close = (np.asarray(a, dtype=float) for a in (high, low, close))
    previous_close = np.empty_like(close)
    previous_close[0] = close[0]
    previous_close[1:] = close[:-1]
    return np.maximum.reduce([
        high - low,
        np.abs(high - previous_close),
        np.abs(low - previous_close),
    ])


def atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int = 14) -> np.ndarray:
    """Average true range - the volatility measure position sizing uses."""
    tr = true_range(high, low, close)
    out = np.full(tr.shape, np.nan)
    if len(tr) < period:
        return out
    out[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        out[i] = (out[i - 1] * (period - 1) + tr[i]) / period
    return out


def roc(values: np.ndarray, period: int = 20) -> np.ndarray:
    """Rate of change, as a fraction."""
    arr = _validate(values, period)
    out = np.full(arr.shape, np.nan)
    if len(arr) <= period:
        return out
    out[period:] = arr[period:] / arr[:-period] - 1.0
    return out


def realised_volatility(values: np.ndarray, period: int = 20) -> np.ndarray:
    """Annualised, from log returns."""
    arr = _validate(values, period)
    out = np.full(arr.shape, np.nan)
    if len(arr) <= period:
        return out
    log_returns = np.diff(np.log(arr))
    for i in range(period, len(arr)):
        out[i] = log_returns[i - period : i].std() * np.sqrt(252)
    return out


def drawdown(values: np.ndarray) -> np.ndarray:
    arr = np.asarray(values, dtype=float)
    peak = np.maximum.accumulate(arr)
    return arr / peak - 1.0


__all__ = [
    "atr",
    "bollinger",
    "drawdown",
    "ema",
    "macd",
    "realised_volatility",
    "roc",
    "rsi",
    "sma",
    "true_range",
]
