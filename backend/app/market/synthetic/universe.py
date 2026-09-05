"""Generates a fictional stock universe.

Everything derives from one master seed, so the same seed always produces the
same companies with the same fundamentals. Sector characteristics (beta,
volatility, dividend behaviour) differ enough that a strategy tuned on one
sector should not transfer for free to another.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

# --- sector characteristics -------------------------------------------------
# beta: sensitivity to the market factor
# vol: annualised idiosyncratic volatility
# div: annual dividend yield
# drift: annualised excess drift, before the market factor


@dataclass(frozen=True)
class SectorProfile:
    name: str
    beta: tuple[float, float]
    vol: tuple[float, float]
    div_yield: tuple[float, float]
    drift: tuple[float, float]
    weight: float


SECTORS: tuple[SectorProfile, ...] = (
    SectorProfile("Technology",       (1.05, 1.60), (0.30, 0.55), (0.000, 0.008), (0.02, 0.09), 0.22),
    SectorProfile("Health Care",      (0.70, 1.15), (0.22, 0.42), (0.005, 0.020), (0.01, 0.06), 0.14),
    SectorProfile("Financials",       (0.95, 1.40), (0.22, 0.38), (0.015, 0.040), (0.00, 0.05), 0.14),
    SectorProfile("Consumer",         (0.65, 1.10), (0.18, 0.32), (0.010, 0.030), (0.00, 0.04), 0.13),
    SectorProfile("Industrials",      (0.85, 1.25), (0.20, 0.34), (0.010, 0.028), (0.00, 0.04), 0.12),
    SectorProfile("Energy",           (0.80, 1.45), (0.30, 0.55), (0.020, 0.055), (-0.03, 0.06), 0.09),
    SectorProfile("Utilities",        (0.30, 0.65), (0.12, 0.22), (0.028, 0.055), (0.00, 0.03), 0.07),
    SectorProfile("Real Estate",      (0.70, 1.10), (0.20, 0.36), (0.025, 0.055), (-0.01, 0.04), 0.05),
    SectorProfile("Materials",        (0.85, 1.30), (0.24, 0.42), (0.012, 0.032), (-0.01, 0.04), 0.04),
)

SECTOR_BY_NAME = {s.name: s for s in SECTORS}

# --- name construction ------------------------------------------------------

_PREFIX = (
    "Nor", "Ald", "Ver", "Cal", "Bry", "Hal", "Ost", "Ken", "Mar", "Tel",
    "Ver", "Sil", "Ash", "Cor", "Dun", "Ely", "Fen", "Gar", "Hol", "Ing",
    "Jar", "Kel", "Lum", "Mer", "Nav", "Orl", "Pen", "Quar", "Rid", "Sef",
    "Thal", "Umb", "Val", "Wex", "Yar", "Zen", "Brae", "Cinder", "Dray", "Ember",
)
_SUFFIX = (
    "ton", "wick", "field", "gate", "ridge", "mont", "dale", "haven", "crest", "ford",
    "bury", "stead", "mark", "point", "vale", "shire", "cliff", "brook", "worth", "hollow",
)
_SECTOR_WORDS: dict[str, tuple[str, ...]] = {
    "Technology":  ("Systems", "Labs", "Compute", "Networks", "Dynamics", "Silicon", "Data"),
    "Health Care": ("Biosciences", "Therapeutics", "Health", "Medical", "Diagnostics", "Pharma"),
    "Financials":  ("Financial", "Capital", "Bancorp", "Trust", "Holdings", "Assurance"),
    "Consumer":    ("Brands", "Retail", "Foods", "Consumer Group", "Provisions", "Goods"),
    "Industrials": ("Industries", "Manufacturing", "Engineering", "Logistics", "Works"),
    "Energy":      ("Energy", "Petroleum", "Resources", "Power", "Drilling", "Fuels"),
    "Utilities":   ("Utilities", "Electric", "Water Works", "Grid", "Power & Light"),
    "Real Estate": ("Properties", "Realty", "Estates", "Land Trust", "Development"),
    "Materials":   ("Materials", "Chemicals", "Mining", "Steel", "Composites"),
}


@dataclass
class Company:
    symbol: str
    name: str
    sector: str
    seed: int
    listed_on: date
    initial_price: float
    shares_outstanding: int
    beta: float
    annual_vol: float
    drift: float
    div_yield: float
    earnings_month_offset: int          # 0-2: which month of the quarter it reports
    quality: float                      # 0-1, biases earnings surprises
    sim_params: dict[str, Any] = field(default_factory=dict)

    @property
    def market_cap(self) -> float:
        return self.initial_price * self.shares_outstanding


def _stable_seed(master_seed: int, symbol: str) -> int:
    """A per-instrument seed that depends only on the master seed and the symbol,
    so adding a company never shifts the price history of the others."""
    h = hashlib.sha256(f"{master_seed}:{symbol}".encode()).digest()
    return int.from_bytes(h[:8], "big") % (2**31 - 1)


def _make_symbol(rng: np.random.Generator, taken: set[str]) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for _ in range(500):
        n = int(rng.choice([3, 4], p=[0.55, 0.45]))
        sym = "".join(rng.choice(list(letters), size=n))
        if sym not in taken:
            taken.add(sym)
            return sym
    raise RuntimeError("exhausted the symbol space")


def _make_name(rng: np.random.Generator, sector: str, taken: set[str]) -> str:
    words = _SECTOR_WORDS[sector]
    for _ in range(500):
        style = rng.random()
        if style < 0.45:
            stem = rng.choice(_PREFIX) + rng.choice(_SUFFIX)
        elif style < 0.8:
            stem = rng.choice(_PREFIX) + rng.choice(_SUFFIX) + " " + rng.choice(_PREFIX)
        else:
            stem = rng.choice(_PREFIX)
        name = f"{stem} {rng.choice(words)}"
        if name not in taken:
            taken.add(name)
            return name
    raise RuntimeError("exhausted the name space")


def generate_universe(
    *,
    count: int = 60,
    master_seed: int = 20260905,
    listing_start: date = date(2015, 1, 2),
) -> list[Company]:
    """Build `count` companies deterministically from `master_seed`."""
    rng = np.random.default_rng(master_seed)
    weights = np.array([s.weight for s in SECTORS], dtype=float)
    weights /= weights.sum()

    symbols: set[str] = set()
    names: set[str] = set()
    companies: list[Company] = []

    for _ in range(count):
        profile = SECTORS[int(rng.choice(len(SECTORS), p=weights))]
        symbol = _make_symbol(rng, symbols)
        name = _make_name(rng, profile.name, names)

        beta = float(rng.uniform(*profile.beta))
        vol = float(rng.uniform(*profile.vol))
        drift = float(rng.uniform(*profile.drift))
        div = float(rng.uniform(*profile.div_yield))

        # Log-uniform price and share count give a realistic mix of small caps
        # and mega caps rather than everything clustering in the middle.
        price = float(np.exp(rng.uniform(np.log(7), np.log(420))))
        shares = int(np.exp(rng.uniform(np.log(2.0e7), np.log(3.0e9))))

        companies.append(
            Company(
                symbol=symbol,
                name=name,
                sector=profile.name,
                seed=_stable_seed(master_seed, symbol),
                listed_on=listing_start,
                initial_price=round(price, 2),
                shares_outstanding=shares,
                beta=round(beta, 3),
                annual_vol=round(vol, 4),
                drift=round(drift, 4),
                div_yield=round(div, 4),
                earnings_month_offset=int(rng.integers(0, 3)),
                quality=float(rng.beta(2.2, 2.2)),
                sim_params={
                    "drift": round(drift, 4),
                    "div_yield": round(div, 4),
                    "quality": round(float(rng.beta(5, 5)), 4),
                    "master_seed": master_seed,
                },
            )
        )

    companies.sort(key=lambda c: c.symbol)
    return companies


__all__ = ["SECTORS", "SECTOR_BY_NAME", "Company", "SectorProfile", "generate_universe"]
