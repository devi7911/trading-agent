# Agentic Trading Desk

An autonomous trading agent. You set targets and a watchlist once; the agent
handles research, sizing, entries, exits and reporting, and talks to you through
notifications rather than screens.

**Execution is simulated. There is no live trading adapter in this repository and
there is not meant to be one.**

The full architecture and the ten-phase plan live in [`docs/`](./docs/).

---

## Where this is

**Phase 05 — the agent trades on its own.** A synthetic market, a simulated
exchange with a reconcilable ledger, rule-based strategies, a risk gate that can
only shrink or refuse, and a loop that runs unattended in its own container.

Nothing here touches real money and nothing here ever will.

| Phase | What | Status |
| ----- | ---- | ------ |
| 00 | Foundation: compose, schema, auth, health | ✅ done |
| 01 | Market data spine: synthetic universe | ✅ done |
| 02 | Simulated exchange: matching engine, order lifecycle | ✅ done |
| 03 | Rule-based strategy engine | ✅ done |
| 04 | Risk gate | ✅ done |
| 05 | Agent orchestrator (the loop) | ✅ done |
| 06 | Angular dashboard | 🟡 market terminal built |
| 07 | Telegram notifications | 🟡 digest generator |
| 08 | LLM reasoning layer | |
| 09 | Backtest & validation harness | 🟡 analytics and reports |
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
| Market terminal | http://localhost:4200/market |
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

### The market terminal

Sign in and go to **/market**:

- **Overview** — cap-weighted index chart, breadth, sector performance over
  1D/1W/1M/3M/YTD/1Y, gainers, losers and most active by relative volume.
- **Instrument detail** — candlestick chart with volume, selectable range,
  risk stats, headlines with sentiment, and earnings history.
- **Exports** — Excel workbook and universe CSV from the overview; bar CSV and
  a PDF tearsheet from any instrument.

```powershell
docker compose exec api python -m app.cli digest   # the daily market summary
```

That digest text is what phase 07 will send to Telegram.

### A compose gotcha, once

`node_modules` lives in a named volume for speed, which means a newly added npm
package is invisible to the running container even after a rebuild — the volume
shadows the image. After adding a frontend dependency:

```powershell
docker compose exec web npm install
docker compose restart web
```

### Running the agent

```powershell
# give a user a watchlist and let the agent act
docker compose exec api python -m app.cli setup-agent --email you@example.com --count 12
docker compose exec api python -m app.cli tick --email you@example.com

# evaluate everything, place nothing
docker compose exec api python -m app.cli tick --email you@example.com --dry-run
```

The `agent` container ticks every 15 minutes on its own. It holds a Redis lock,
so starting two of them by accident is harmless.

**The kill switch lives outside the agent**, in Redis, so it works even when the
loop is wedged:

```
POST   /api/v1/agent/halt      engage
DELETE /api/v1/agent/halt      release
GET    /api/v1/agent/halt      status
```

### How a decision is made

```
perceive -> enrich -> recall -> reason -> GATE -> execute -> observe -> report
```

The gate is the part that matters. It is a pure function of (Intent,
RiskContext) — no database, no clock, no network, and no language model. It can
shrink an order to fit a cap, or refuse it with a reason code, and it can never
make one bigger. Every verdict is stored with its full check trace, so any
decision can be explained months later:

```powershell
curl /api/v1/agent/runs                     # every tick
curl /api/v1/agent/runs/{id}/decisions      # every symbol considered, and why
curl /api/v1/trading/reconcile              # rebuild cash and positions from fills
```

### Two clocks

Wall time and market time are not the same thing, and conflating them is a bug.
With daily bars they differ by up to three days over a weekend. In simulation
the **market clock** is authoritative: the agent runs mid-session on the day of
the most recent bar, and staleness is measured in trading sessions rather than
seconds — a Friday close is not stale on Monday morning.

### Phase 01 acceptance

1. `seed-market` loads ~90k bars for 60 instruments without error.
2. Running it a second time changes no row counts and no prices.
3. `GET /api/v1/market/instruments/{symbol}/bars` returns plausible OHLCV.
4. A chart of a synthetic stock is indistinguishable from a real one — check it
   yourself at `/instrument/<symbol>`.

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
    agent/       the loop, market clock, context builder, worker
    core/        config, logging, db, security
    execution/   broker port, matching engine, order lifecycle
    market/      calendar, provider port, synthetic generator, ingestion
    risk/        the gate and its types
    strategy/    indicators, signals, strategies
    models/      SQLAlchemy models (the schema is the contract)
    schemas/     Pydantic request/response models
    api/v1/      routers
    services/    business logic, no HTTP concerns
  alembic/       versioned migrations
  tests/
frontend/
  src/app/
    core/        auth service, interceptor, guard, market service, models
    pages/       login, signup, dashboard, market, instrument
    shared/      app shell, chart theming, formatting helpers
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
- Autonomy starts at `observe`: the agent logs what it would do and places nothing.
- Fills are the only thing that moves cash or position; positions are derived and
  never edited, so the ledger can always be rebuilt and compared.
- The risk gate has property-based test coverage: no generated input has been
  able to talk it past a cap.

## A note on scope

Simulated results overstate real ones — always. This repository is an engineering
exercise, not investment advice, and nothing here should be treated as a reason to
trust a system with actual money.
