"""Market-wide analytics computed from the bar store.

Everything here is derived, never authoritative - `bars` is the source of truth
and any of this can be rebuilt from scratch. Loading the full panel into numpy
is deliberate: at 60 instruments x 1500 days it is a few megabytes, and vector
maths over the whole panel is far simpler to get right than window functions.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.models import Bar, Instrument, MarketSnapshot

log = get_logger(__name__)

TRADING_DAYS = 252
INDEX_BASE = 1000.0
HIGH_LOW_WINDOW = 252   # "52-week" high and low
MA_WINDOW = 50


@dataclass
class Panel:
    """The bar store as aligned arrays. Rows are days, columns are instruments."""

    days: list[datetime]
    symbols: list[str]
    ids: list
    sectors: list[str | None]
    shares: np.ndarray          # (n_instruments,)
    close: np.ndarray           # (n_days, n_instruments)
    volume: np.ndarray

    @property
    def returns(self) -> np.ndarray:
        """Simple daily returns, first row zero."""
        out = np.zeros_like(self.close)
        out[1:] = self.close[1:] / self.close[:-1] - 1.0
        return out


async def load_panel(session: AsyncSession, timeframe: str = "1d") -> Panel | None:
    """Pull every bar into a dense matrix. Returns None if nothing is loaded."""
    stmt = (
        select(
            Bar.ts,
            Instrument.symbol,
            Instrument.id,
            Instrument.sector,
            Instrument.shares_outstanding,
            Bar.close,
            Bar.volume,
        )
        .join(Instrument, Instrument.id == Bar.instrument_id)
        .where(Bar.timeframe == timeframe)
        .order_by(Bar.ts, Instrument.symbol)
    )
    rows = (await session.execute(stmt)).all()
    if not rows:
        return None

    days = sorted({r[0] for r in rows})
    symbols = sorted({r[1] for r in rows})
    day_ix = {d: i for i, d in enumerate(days)}
    sym_ix = {s: j for j, s in enumerate(symbols)}

    close = np.full((len(days), len(symbols)), np.nan)
    volume = np.zeros((len(days), len(symbols)), dtype=np.int64)
    shares = np.ones(len(symbols))
    ids: list = [None] * len(symbols)
    sectors: list[str | None] = [None] * len(symbols)

    for ts, symbol, iid, sector, sh, c, v in rows:
        i, j = day_ix[ts], sym_ix[symbol]
        close[i, j] = float(c)
        volume[i, j] = int(v)
        ids[j] = iid
        sectors[j] = sector
        shares[j] = float(sh or 1)

    # Carry the last known price across any gap, then back-fill the very start.
    for j in range(close.shape[1]):
        col = close[:, j]
        missing = np.isnan(col)
        if missing.all():
            col[:] = 1.0
            continue
        idx = np.where(~missing, np.arange(len(col)), 0)
        np.maximum.accumulate(idx, out=idx)
        col[:] = col[idx]
        first = np.argmax(~missing)
        col[:first] = col[first]

    return Panel(days, symbols, ids, sectors, shares, close, volume)


def _rolling_extreme(a: np.ndarray, window: int, *, maximum: bool) -> np.ndarray:
    """Trailing rolling max/min, expanding until the window fills."""
    n = a.shape[0]
    out = np.empty_like(a)
    fn = np.max if maximum else np.min
    for t in range(n):
        lo = max(0, t - window + 1)
        out[t] = fn(a[lo : t + 1], axis=0)
    return out


def _rolling_mean(a: np.ndarray, window: int) -> np.ndarray:
    n = a.shape[0]
    out = np.empty_like(a)
    cumulative = np.cumsum(a, axis=0)
    for t in range(n):
        lo = max(0, t - window + 1)
        total = cumulative[t] - (cumulative[lo - 1] if lo > 0 else 0)
        out[t] = total / (t - lo + 1)
    return out


def compute_snapshots(panel: Panel) -> list[dict]:
    """Cap-weighted index plus breadth, one row per trading day."""
    close, volume, shares = panel.close, panel.volume, panel.shares

    market_cap = close * shares
    total_cap = market_cap.sum(axis=1)
    index = INDEX_BASE * total_cap / total_cap[0]

    index_return = np.zeros_like(index)
    index_return[1:] = index[1:] / index[:-1] - 1.0

    daily = np.zeros_like(close)
    daily[1:] = close[1:] / close[:-1] - 1.0

    advancers = (daily > 0.0005).sum(axis=1)
    decliners = (daily < -0.0005).sum(axis=1)
    unchanged = close.shape[1] - advancers - decliners

    highs = _rolling_extreme(close, HIGH_LOW_WINDOW, maximum=True)
    lows = _rolling_extreme(close, HIGH_LOW_WINDOW, maximum=False)
    new_highs = (close >= highs - 1e-9).sum(axis=1)
    new_lows = (close <= lows + 1e-9).sum(axis=1)

    ma = _rolling_mean(close, MA_WINDOW)
    pct_above = (close > ma).sum(axis=1) / close.shape[1] * 100.0

    # Regime is inferred, not read from the generator - the app should not need
    # to know it was simulated. 60-day index return decides.
    regimes: list[str] = []
    for t in range(len(index)):
        lo = max(0, t - 60)
        change = index[t] / index[lo] - 1.0
        regimes.append("bull" if change > 0.05 else "bear" if change < -0.05 else "chop")

    return [
        {
            "ts": panel.days[t],
            "index_value": round(float(index[t]), 4),
            "index_return": round(float(index_return[t]), 6),
            "advancers": int(advancers[t]),
            "decliners": int(decliners[t]),
            "unchanged": int(unchanged[t]),
            "new_highs": int(new_highs[t]),
            "new_lows": int(new_lows[t]),
            "pct_above_50dma": round(float(pct_above[t]), 2),
            "total_volume": int(volume[t].sum()),
            "regime": regimes[t],
        }
        for t in range(len(panel.days))
    ]


async def rebuild_snapshots(session: AsyncSession) -> int:
    panel = await load_panel(session)
    if panel is None:
        log.warning("no_bars_loaded")
        return 0

    rows = compute_snapshots(panel)
    for i in range(0, len(rows), 2_000):
        chunk = rows[i : i + 2_000]
        stmt = insert(MarketSnapshot).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=[MarketSnapshot.ts],
            set_={
                c: stmt.excluded[c]
                for c in (
                    "index_value", "index_return", "advancers", "decliners", "unchanged",
                    "new_highs", "new_lows", "pct_above_50dma", "total_volume", "regime",
                )
            },
        )
        await session.execute(stmt)
    log.info("snapshots_rebuilt", days=len(rows))
    return len(rows)


# --- derived views used by the API ------------------------------------------

WINDOWS = {"1d": 1, "1w": 5, "1m": 21, "3m": 63, "ytd": None, "1y": 252}


def _window_start(panel: Panel, window: str) -> int:
    n = len(panel.days)
    if window == "ytd":
        year = panel.days[-1].year
        for i, d in enumerate(panel.days):
            if d.year == year:
                return max(0, i - 1)
        return 0
    span = WINDOWS.get(window, 1) or 1
    return max(0, n - 1 - span)


def sector_performance(panel: Panel, window: str = "1d") -> list[dict]:
    start = _window_start(panel, window)
    change = panel.close[-1] / panel.close[start] - 1.0

    buckets: dict[str, list[int]] = {}
    for j, sector in enumerate(panel.sectors):
        buckets.setdefault(sector or "Unclassified", []).append(j)

    out = []
    for sector, cols in buckets.items():
        weights = panel.shares[cols] * panel.close[start, cols]
        weights = weights / weights.sum()
        out.append(
            {
                "sector": sector,
                "constituents": len(cols),
                "return_pct": round(float(np.dot(change[cols], weights) * 100), 2),
                "median_return_pct": round(float(np.median(change[cols]) * 100), 2),
                "advancers": int((change[cols] > 0).sum()),
                "decliners": int((change[cols] <= 0).sum()),
            }
        )
    out.sort(key=lambda r: r["return_pct"], reverse=True)
    return out


def movers(panel: Panel, window: str = "1d", limit: int = 10) -> dict[str, list[dict]]:
    start = _window_start(panel, window)
    change = panel.close[-1] / panel.close[start] - 1.0

    avg_volume = panel.volume[-21:].mean(axis=0)
    rel_volume = np.divide(
        panel.volume[-1], avg_volume, out=np.ones_like(avg_volume, dtype=float),
        where=avg_volume > 0,
    )

    def rows(order: np.ndarray) -> list[dict]:
        return [
            {
                "symbol": panel.symbols[j],
                "sector": panel.sectors[j],
                "close": round(float(panel.close[-1, j]), 2),
                "change_pct": round(float(change[j] * 100), 2),
                "volume": int(panel.volume[-1, j]),
                "relative_volume": round(float(rel_volume[j]), 2),
            }
            for j in order
        ]

    ranked = np.argsort(change)
    return {
        "gainers": rows(ranked[::-1][:limit]),
        "losers": rows(ranked[:limit]),
        "most_active": rows(np.argsort(rel_volume)[::-1][:limit]),
    }


def instrument_stats(panel: Panel, symbol: str, lookback: int = 252) -> dict:
    j = panel.symbols.index(symbol)
    series = panel.close[-lookback:, j] if lookback else panel.close[:, j]
    rets = np.diff(series) / series[:-1]

    ann_return = float((series[-1] / series[0]) ** (TRADING_DAYS / len(series)) - 1)
    ann_vol = float(rets.std() * np.sqrt(TRADING_DAYS))
    peak = np.maximum.accumulate(series)
    drawdown = series / peak - 1.0

    up_days = int((rets > 0).sum())
    return {
        "symbol": symbol,
        "lookback_days": len(series),
        "last": round(float(series[-1]), 2),
        "period_return_pct": round(float(series[-1] / series[0] - 1) * 100, 2),
        "annualised_return_pct": round(ann_return * 100, 2),
        "annualised_vol_pct": round(ann_vol * 100, 2),
        "sharpe": round(ann_return / ann_vol, 2) if ann_vol > 1e-9 else None,
        "max_drawdown_pct": round(float(drawdown.min()) * 100, 2),
        "current_drawdown_pct": round(float(drawdown[-1]) * 100, 2),
        "best_day_pct": round(float(rets.max()) * 100, 2),
        "worst_day_pct": round(float(rets.min()) * 100, 2),
        "up_day_pct": round(up_days / len(rets) * 100, 1),
        "avg_volume": int(panel.volume[-lookback:, j].mean()),
    }


def correlation_matrix(panel: Panel, symbols: list[str], lookback: int = 252) -> dict:
    cols = [panel.symbols.index(s) for s in symbols]
    rets = np.diff(panel.close[-lookback:, cols], axis=0) / panel.close[-lookback:-1, cols]
    matrix = np.corrcoef(rets, rowvar=False)
    return {
        "symbols": symbols,
        "lookback_days": lookback,
        "matrix": [[round(float(v), 3) for v in row] for row in np.atleast_2d(matrix)],
    }


__all__ = [
    "Panel",
    "compute_snapshots",
    "correlation_matrix",
    "instrument_stats",
    "load_panel",
    "movers",
    "rebuild_snapshots",
    "sector_performance",
]
