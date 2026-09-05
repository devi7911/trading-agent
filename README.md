# Agentic Trading Desk

An autonomous trading agent. You set targets and a watchlist once; the agent
handles research, sizing, entries, exits and reporting, and talks to you through
notifications rather than screens.

**Execution is simulated. There is no live trading adapter in this repository and
there is not meant to be one.**

The full architecture and the ten-phase plan live in [`docs/`](./docs/).

---

## Where this is

**Phase 01 — market data spine.** A complete synthetic market: 60 fictional
companies across 9 sectors, six years of daily bars, a news wire and corporate
events, all reproducible from a single seed. No agent and no orders yet.

| Phase | What | Status |
| ----- | ---- | ------ |
| 00 | Foundation: compose, schema, auth, health | ✅ done |
| 01 | Market data spine: synthetic universe | ✅ done |
| 02 | Simulated exchange: matching engine, order lifecycle | next |
| 03 | Rule-based strategy engine | |
| 04 | Risk gate | |
| 05 | Agent orchestrator (the loop) | |
| 06 | Angular dashboard | |
| 07 | Telegram notifications | |
| 08 | LLM reasoning layer | |
| 09 | Backtest & validation harness | |
| 10 | Hardening & Alpaca paper swap | |

---

## Prerequisites

- **Docker Desktop** (with the WSL2 backend) — the only hard requirement
- Optional for working outside containers: Python 3.12+, Node 22+, Angular CLI

## Running it

```powershell
copy .env.example .env
# then edit .env and set SECRET_KEY to something random:
#   python -c "import secrets; print(secrets.token_urlsafe(48))"

docker compose up --build
```

| Service | URL |
| ------- | --- |
| Web app | http://localhost:4200 |
| API docs | http://localhost:8000/docs |
| Readiness | http://localhost:8000/api/v1/health/ready |
| Postgres | localhost:5432 |
| Redis | localhost:6379 |

Migrations run automatically on API start.

### Seeding a market

```powershell
docker compose exec api python -m app.cli seed-market --count 60 --years 6
docker compose exec api python -m app.cli market-stats
```

Same seed, same market — always. The seed is idempotent: run it twice and row
counts do not change.

| Option | Default | Meaning |
| ------ | ------- | ------- |
| `--count` | 60 | How many companies to generate |
| `--years` | 6 | How much history |
| `--seed` | 20260905 | Master seed. Change it for a different market |
| `--end` | today | End date, `YYYY-MM-DD` |

### What the generator produces

Not independent random walks — those make diversification look free and
momentum look easy. Instead:

```
return = drift + beta x market + load x sector + idiosyncratic
```

- **Regime switching.** The market factor moves between bull / chop / bear
  through a sticky Markov chain, so regimes persist for months.
- **Volatility clustering.** Idiosyncratic vol follows a GARCH(1,1) recursion,
  which is what makes returns fat-tailed rather than normal.
- **Sector structure.** Technology carries the highest beta and volatility,
  Utilities the lowest, and same-sector names correlate more than cross-sector
  ones. All of this is asserted in the tests.
- **Earnings jumps.** Quarterly reports with surprises, and a nonlinear
  reaction — small beats barely move, big misses gap hard.
- **A news wire with ground truth.** Every headline is tagged `leading`
  (published before the move it describes), `lagging` (after) or `noise`.
  Roughly 19 / 56 / 25 in a default seed. Because the label is stored, you can
  score exactly how well a news-reading agent did rather than taking its word.

### Phase 00 acceptance

1. `docker compose up` finishes with four healthy containers.
2. `GET /api/v1/health/ready` returns `{"status":"ok"}` with Postgres and Redis both `ok`.
3. You can create an account at http://localhost:4200/signup and land on the dashboard.
4. `docker compose exec api pytest` passes.

### Phase 01 acceptance

1. `seed-market` loads ~90k bars for 60 instruments without error.
2. Running it a second time changes no row counts and no prices.
3. `GET /api/v1/market/instruments/{symbol}/bars` returns plausible OHLCV.
4. A chart of a synthetic stock is indistinguishable from a real one.

## Common commands

```powershell
docker compose up --build          # start everything
docker compose logs -f api         # follow API logs
docker compose exec api pytest     # run the full suite, integration tests included
docker compose exec api ruff check .
docker compose exec api alembic revision --autogenerate -m "description"
docker compose exec api alembic upgrade head
docker compose down -v             # stop and wipe the volumes
```

## Layout

```
backend/
  app/
    core/        config, logging, db, security
    market/      calendar, provider port, synthetic generator, ingestion
    models/      SQLAlchemy models (the schema is the contract)
    schemas/     Pydantic request/response models
    api/v1/      routers
    services/    business logic, no HTTP concerns
  alembic/       versioned migrations
  tests/
frontend/
  src/app/
    core/        auth service, interceptor, guard, models
    pages/       login, signup, dashboard
infra/           database init
docs/            architecture and phase plan
```

## Safety rails already in place

- `ALLOW_LIVE_TRADING` defaults to `false` and no live adapter exists.
- Accounts carry an `is_halted` flag the risk gate will honour from phase 04.
- Policies are versioned, never edited in place, so every future decision can name
  the exact policy that governed it.
- `SYSTEM_CEILINGS` in `app/models/policy.py` caps what any user policy may allow.
- `audit_log` is append-only and sufficient to reconstruct account state from zero.

## A note on scope

Simulated results overstate real ones — always. This repository is an engineering
exercise, not investment advice, and nothing here should be treated as a reason to
trust a system with actual money.
