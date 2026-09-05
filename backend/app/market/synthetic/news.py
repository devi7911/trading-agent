"""Synthetic news wire.

The point is not realistic prose - it is realistic *signal structure*. Every
item is tagged with ground truth in `relation`:

  leading  - published before the move it describes (genuinely predictive)
  lagging  - published after the move (explains, predicts nothing)
  noise    - unrelated to any move (a decoy)

A news-reading agent that cannot beat the noise floor here is not reading news,
it is pattern-matching sentiment words. Because `relation` is stored, you can
score exactly how well it did.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from app.market.synthetic.prices import PricePanel
from app.market.synthetic.universe import Company

# --- headline templates -----------------------------------------------------

_POSITIVE = (
    "{name} lifts full-year guidance on stronger {sector_word} demand",
    "{name} wins multi-year contract worth an estimated ${amount}M",
    "Analysts at Kettering Rowe upgrade {name} to Buy, citing margin recovery",
    "{name} announces buyback of up to ${amount}M in shares",
    "{name} expands {sector_word} capacity after record quarterly orders",
    "{name} names industry veteran as chief operating officer",
    "{name} settles long-running dispute, removing an overhang",
)

_NEGATIVE = (
    "{name} cuts full-year outlook as {sector_word} orders soften",
    "{name} discloses accounting review; shares under pressure",
    "Analysts at Kettering Rowe downgrade {name} on valuation concerns",
    "{name} delays flagship {sector_word} programme by two quarters",
    "Regulator opens inquiry into {name} disclosure practices",
    "{name} chief financial officer departs unexpectedly",
    "{name} warns of margin compression from input costs",
)

_NEUTRAL = (
    "{name} to present at the Halloway {sector_word} Conference",
    "{name} publishes annual sustainability report",
    "{name} completes previously announced refinancing",
    "{name} schedules quarterly results for later this month",
    "{name} appoints two independent directors to the board",
)

_SECTOR_WORD = {
    "Technology": "compute",
    "Health Care": "clinical",
    "Financials": "lending",
    "Consumer": "retail",
    "Industrials": "manufacturing",
    "Energy": "production",
    "Utilities": "grid",
    "Real Estate": "leasing",
    "Materials": "processing",
}

_MACRO_POSITIVE = (
    "Risk appetite returns as growth data beats expectations",
    "Broad rally lifts {sector} names to multi-month highs",
    "Investors rotate back into {sector} on easing cost pressure",
)
_MACRO_NEGATIVE = (
    "Selling accelerates as growth concerns spread across {sector}",
    "{sector} names lead declines in a broad risk-off session",
    "Funds trim {sector} exposure amid tightening conditions",
)


@dataclass
class NewsDraft:
    symbol: str | None
    published_at: date
    headline: str
    body: str
    category: str
    sentiment: float
    relation: str


def _fmt(template: str, company: Company, rng: np.random.Generator) -> str:
    return template.format(
        name=company.name,
        sector=company.sector,
        sector_word=_SECTOR_WORD.get(company.sector, "core"),
        amount=int(rng.integers(15, 900)),
    )


def generate_news(
    companies: list[Company],
    panel: PricePanel,
    *,
    master_seed: int = 20260905,
    move_threshold: float = 2.0,
    leading_fraction: float = 0.35,
    noise_per_day: float = 0.6,
) -> list[NewsDraft]:
    """Produce the wire for the whole simulated period.

    `leading_fraction` is the share of move-related stories published *before*
    the move. Lower it to make the news feed less useful; raise it to make a
    news-reading agent look smarter than it is.
    """
    rng = np.random.default_rng(master_seed ^ 0x4E5)
    drafts: list[NewsDraft] = []
    days = panel.days

    for i, company in enumerate(companies):
        closes = panel.close[:, i]
        rets = np.diff(np.log(closes), prepend=np.log(closes[0]))
        sigma = float(np.std(rets[rets != 0])) or 0.02
        crng = np.random.default_rng(company.seed ^ 0x4E5)

        # --- earnings coverage: a preview before, a result after ---
        for report_day, estimate, actual in panel.earnings.get(company.symbol, []):
            beat = actual >= estimate
            drafts.append(
                NewsDraft(
                    symbol=company.symbol,
                    published_at=report_day - timedelta(days=3),
                    headline=f"Preview: {company.name} expected to post ${estimate:.2f} a share",
                    body=f"Consensus stands at ${estimate:.2f}. The company has reported in line "
                         f"or better in recent quarters.",
                    category="earnings_preview",
                    sentiment=0.0,
                    relation="noise",  # a preview genuinely predicts nothing
                )
            )
            drafts.append(
                NewsDraft(
                    symbol=company.symbol,
                    published_at=report_day,
                    headline=(
                        f"{company.name} {'beats' if beat else 'misses'} with ${actual:.2f} "
                        f"a share against ${estimate:.2f} expected"
                    ),
                    body=f"Reported earnings of ${actual:.2f} per share versus ${estimate:.2f} "
                         f"expected, a {'beat' if beat else 'miss'} of "
                         f"{abs(actual - estimate) / estimate * 100:.1f}%.",
                    category="earnings",
                    sentiment=float(np.clip((actual - estimate) / estimate * 4, -1, 1)),
                    relation="lagging",
                )
            )

        # --- coverage of large moves ---
        big = np.flatnonzero(np.abs(rets) > move_threshold * sigma)
        for t in big:
            if days[t] in {d for d, _, _ in panel.earnings.get(company.symbol, [])}:
                continue  # earnings already explained this one
            move = float(rets[t])
            positive = move > 0
            leads = crng.random() < leading_fraction
            published = days[t - 1] if (leads and t > 0) else days[t]
            template = crng.choice(_POSITIVE if positive else _NEGATIVE)
            drafts.append(
                NewsDraft(
                    symbol=company.symbol,
                    published_at=published,
                    headline=_fmt(str(template), company, crng),
                    body=f"Shares of {company.name} ({company.symbol}) moved "
                         f"{move * 100:+.1f}% on the session.",
                    category="company",
                    sentiment=float(np.clip(move / (3 * sigma), -1, 1)),
                    relation="leading" if leads else "lagging",
                )
            )

        # --- decoys: neutral filings and appearances, unrelated to any move ---
        n_noise = crng.poisson(noise_per_day * len(days) / 90)
        for _ in range(int(n_noise)):
            t = int(crng.integers(0, len(days)))
            drafts.append(
                NewsDraft(
                    symbol=company.symbol,
                    published_at=days[t],
                    headline=_fmt(str(crng.choice(_NEUTRAL)), company, crng),
                    body="Routine corporate disclosure.",
                    category="filing",
                    sentiment=float(crng.normal(0, 0.12)),
                    relation="noise",
                )
            )

    # --- macro colour, tied to the actual regime that day ---
    sectors = sorted({c.sector for c in companies})
    for t, d in enumerate(days):
        if rng.random() > 0.22:
            continue
        regime = int(panel.regimes[t])
        sector = str(rng.choice(sectors))
        if regime == 0:
            template, sentiment = str(rng.choice(_MACRO_POSITIVE)), 0.4
        elif regime == 2:
            template, sentiment = str(rng.choice(_MACRO_NEGATIVE)), -0.4
        else:
            continue
        drafts.append(
            NewsDraft(
                symbol=None,
                published_at=d,
                headline=template.format(sector=sector),
                body="Market wrap.",
                category="macro",
                sentiment=sentiment,
                relation="lagging",
            )
        )

    drafts.sort(key=lambda n: (n.published_at, n.symbol or ""))
    return drafts


__all__ = ["NewsDraft", "generate_news"]
