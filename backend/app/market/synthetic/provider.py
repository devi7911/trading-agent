"""Synthetic market data provider.

Generates a complete fictional market from a single seed: companies, daily
bars, a news wire and corporate events. No network, no keys, no rate limits,
and the same seed always yields the same market.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time
from functools import cached_property

from app.market.calendar import session_close_utc, trading_days
from app.market.provider import BarSpec, EventSpec, InstrumentSpec, NewsSpec
from app.market.synthetic.news import generate_news
from app.market.synthetic.prices import PricePanel, simulate
from app.market.synthetic.universe import Company, generate_universe

# News is stamped after the close of the day it is published on.
_WIRE_TIME = time(21, 30)


class SyntheticProvider:
    name = "synthetic"

    def __init__(
        self,
        *,
        count: int = 60,
        seed: int = 20260905,
        start: date = date(2015, 1, 2),
        end: date | None = None,
    ) -> None:
        self.count = count
        self.seed = seed
        self.start = start
        self.end = end or date.today()
        if self.end <= self.start:
            raise ValueError("end must be after start")

    # --- generation (computed once, then reused) ---

    @cached_property
    def companies(self) -> list[Company]:
        return generate_universe(count=self.count, master_seed=self.seed, listing_start=self.start)

    @cached_property
    def days(self) -> list[date]:
        return trading_days(self.start, self.end)

    @cached_property
    def panel(self) -> PricePanel:
        return simulate(self.companies, self.days, master_seed=self.seed)

    # --- provider interface ---

    def instruments(self) -> list[InstrumentSpec]:
        return [
            InstrumentSpec(
                symbol=c.symbol,
                name=c.name,
                sector=c.sector,
                exchange="SIM",
                is_synthetic=True,
                initial_price=c.initial_price,
                shares_outstanding=c.shares_outstanding,
                beta=c.beta,
                annual_vol=c.annual_vol,
                listed_on=c.listed_on,
                generator_seed=c.seed,
                sim_params=c.sim_params,
            )
            for c in self.companies
        ]

    def bars(self, start: date, end: date, timeframe: str = "1d") -> list[BarSpec]:
        if timeframe != "1d":
            raise ValueError("the synthetic provider currently generates daily bars only")
        panel = self.panel
        out: list[BarSpec] = []
        for t, day in enumerate(panel.days):
            if day < start or day > end:
                continue
            ts = session_close_utc(day)
            for i, symbol in enumerate(panel.symbols):
                out.append(
                    BarSpec(
                        symbol=symbol,
                        ts=ts,
                        timeframe=timeframe,
                        open=float(panel.open[t, i]),
                        high=float(panel.high[t, i]),
                        low=float(panel.low[t, i]),
                        close=float(panel.close[t, i]),
                        volume=int(panel.volume[t, i]),
                    )
                )
        return out

    def news(self, start: date, end: date) -> list[NewsSpec]:
        drafts = generate_news(self.companies, self.panel, master_seed=self.seed)
        return [
            NewsSpec(
                symbol=d.symbol,
                published_at=datetime.combine(d.published_at, _WIRE_TIME, tzinfo=UTC),
                headline=d.headline,
                body=d.body,
                category=d.category,
                sentiment=d.sentiment,
                relation=d.relation,
            )
            for d in drafts
            if start <= d.published_at <= end
        ]

    def corporate_events(self, start: date, end: date) -> list[EventSpec]:
        out: list[EventSpec] = []
        by_symbol = {c.symbol: c for c in self.companies}

        for symbol, reports in self.panel.earnings.items():
            for day, estimate, actual in reports:
                if not (start <= day <= end):
                    continue
                out.append(
                    EventSpec(
                        symbol=symbol,
                        event_type="earnings",
                        occurs_at=session_close_utc(day),
                        eps_estimate=estimate,
                        eps_actual=actual,
                        note="beat" if actual >= estimate else "miss",
                    )
                )

        # Quarterly dividends, sized from the company's yield. Recorded as events;
        # prices are not adjusted for them in this phase.
        for symbol, company in by_symbol.items():
            if company.div_yield <= 0.002:
                continue
            per_quarter = company.initial_price * company.div_yield / 4
            for day, _, _ in self.panel.earnings.get(symbol, []):
                if not (start <= day <= end):
                    continue
                out.append(
                    EventSpec(
                        symbol=symbol,
                        event_type="dividend",
                        occurs_at=session_close_utc(day),
                        amount=round(per_quarter, 4),
                        note="quarterly cash dividend",
                    )
                )

        out.sort(key=lambda e: (e.occurs_at, e.symbol))
        return out


__all__ = ["SyntheticProvider"]
