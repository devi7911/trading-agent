# Agentic Trading Desk

An autonomous trading agent. You set targets and a watchlist once; the agent
handles research, sizing, entries, exits and reporting, and talks to you through
notifications rather than screens.

**Execution is simulated. There is no live trading adapter in this repository and
there is not meant to be one.**

The full architecture and the ten-phase plan live in [`docs/`](./docs/).

---

## Where this is

**All ten phases are built.** A synthetic market, a simulated exchange with a
reconcilable ledger, rule-based strategies, a risk gate that can only shrink or
refuse, an agent loop running unattended, a point-in-time backtester, an optional
LLM reviewer, Telegram notifications, and a dashboard.

Nothing here touches real money and nothing here ever will: no adapter in this
repository reports `supports_live_trading`, and pointing one at a live venue
raises rather than connects.

| Phase | What | Status |
| ----- | ---- | ------ |
| 00 | Foundation: compose, schema, auth, health | ✅ done |
| 01 | Market data spine: synthetic universe | ✅ done |
| 02 | Simulated exchange: matching engine, order lifecycle | ✅ done |
| 03 | Rule-based strategy engine | ✅ done |
| 04 | Risk gate | ✅ done |
| 05 | Agent orchestrator (the loop) | ✅ done |
| 06 | Angular dashboard | ✅ done |
| 07 | Telegram notifications | ✅ done |
| 08 | LLM reasoning layer | ✅ done |
| 09 | Backtest & validation harness | ✅ done |
| 10 | Hardening & Alpaca paper swap | ✅ done |

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
| Metrics (Prometheus) | http://localhost:8000/api/v1/health/metrics |
| Live quote stream | http://localhost:8000/api/v1/market/stream |
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

And do not run a production build inside the `web` container: `ng build`
writes `dist/` into the directory the dev server is watching, so vite rebuilds,
which changes `dist/` again, and the page reloads in a loop until you delete
it. Build in a scratch output directory, or stop `web` first.

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

### Does it actually make money?

Ask it, and be willing to hear no:

```powershell
docker compose exec api python -m app.cli backtest --days 400 --universe 10
docker compose exec api python -m app.cli backtest --days 700 --walk-forward
```

The backtester drives the **same** loop, gate and exchange rather than
re-implementing them, one simulated session at a time with an `as_of` cutoff so
it can never see tomorrow's price. It reports against equal-weight buy-and-hold,
names the constraint that blocked the most trades, and block-bootstraps the
return series to show how much was luck.

On the default synthetic market it currently **loses to buy-and-hold** — roughly
46% against 111% over 277 sessions — at about half the volatility and half the
drawdown. That is the honest answer for a capped, partly-invested, risk-managed
agent in a violent bull market, and it is reported rather than tuned away.

### The reasoning layer

Off by default. When enabled it reviews decisions the rules have already made:

```powershell
ollama pull llama3.2:1b
# set LLM_ENABLED=true in .env, then restart
```

The model may agree, temper conviction, or downgrade to hold. **It may not flip
the direction.** If the rules say buy and the model says sell, the answer is the
rules' buy with the review discarded — so a hallucination can block a trade but
never originate one. Every failure mode falls back to the rules rather than
blocking the loop.

### Notifications

```powershell
# create a bot with @BotFather, put the token in .env as TELEGRAM_BOT_TOKEN
docker compose exec api python -m app.cli digest
```

Commands are read-only or safety-increasing by design: `/status`, `/positions`,
`/pnl`, `/explain SYMBOL`, `/halt`, `/resume`. There is deliberately no command
that raises a limit, increases autonomy, or places a trade — anyone who gets hold
of the chat can make the system safer, never bolder.

Without a token the bot idles and notifications are still recorded and visible in
the app. The agent never learns whether push is configured.

### The live market

A `ticker` container keeps the simulated market moving. It advances a session
clock, generates intraday prices from each instrument's own volatility, and when
a session finishes writes it as a new daily bar and opens the next one — so
history keeps growing and the agent always has a fresh session to trade.

Time is compressed: **one real second is three simulated minutes**, so a
390-minute session plays out in a little over two minutes. The dashboard
subscribes over server-sent events and revalues positions and equity as prices
move, with no refresh.

```powershell
docker compose logs -f ticker                    # watch sessions open and close
curl http://localhost:8000/api/v1/market/clock   # where the session has got to
docker compose exec redis redis-cli set market:ticker:paused 1   # freeze it
docker compose exec redis redis-cli del market:ticker:paused     # resume
```

The stream endpoint is **unauthenticated on purpose** and carries market prices
only. `EventSource` cannot send an `Authorization` header, and the usual
workaround — a bearer token in the query string — writes a credential into
browser history and proxy logs. Account data stays on the authenticated API and
is revalued in the browser from these prices.

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
    agent/       the loop, market clock, context builder, worker, reconciler
    backtest/    point-in-time replay, metrics, walk-forward, A/B
    core/        config, logging, db, security, metrics
    execution/   broker port, matching engine, order lifecycle, alpaca adapter
    market/      calendar, provider port, synthetic generator, ingestion
    notify/      telegram client, severity routing, bot worker
    reasoning/   llm client, response schema, the reviewer
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
    pages/       login, signup, portfolio, agent, market, instrument, settings
    shared/      app shell, chart theming, formatting helpers
infra/           database init
docs/            architecture and phase plan
```

`docs/how-it-was-built.html` is the working-session record: every prompt that
produced this repository, in order, and what each one turned into - including
the four one-line questions that each turned up a real bug. Open it in a
browser.

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
- A reconciliation sweep runs every worker cycle; a mismatch halts the account
  and notifies, because an agent trading on a wrong balance compounds the error
  with every order.
- The LLM may only agree with or downgrade a rule-based decision, never flip it.
- Pointing the Alpaca adapter at a live URL raises `LiveTradingRefused`. Reaching
  a live venue is not a configuration change.

## Branches and environments

Promotion runs `dev` -> `sit` -> `pat` -> `main`, by pull request at each step.

| Branch | Environment | Gate |
|---|---|---|
| `dev`  | Dev | none - promotes on a green build |
| `sit`  | SIT | the pull request merge |
| `pat`  | PAT | the pull request merge |
| `main` | -   | the release trunk; no promote job |

Each environment is scoped to its own branch, so a `dev` build cannot deploy to
PAT even by mistake. The intended gate on SIT and PAT is a required reviewer on
the environment, which GitHub does not offer for a private repository on the
Free plan - neither environment protection rules nor branch rulesets can be
created. Until the repo is public or on a paid plan, the only real gate is the
human opening and merging the promotion pull request. Do not read a green
`Promote to sit` job as "someone approved this"; nobody did.

CI runs on every push and pull request to all four: ruff, `alembic upgrade head`
and the full backend suite against a real TimescaleDB and Redis, plus the
frontend production build. The build is the type check that counts - the dev
server tolerates things the optimiser silently erases.

Per-environment settings are GitHub Environment secrets, not files in the repo.
`SECRET_KEY` in CI is a throwaway that only satisfies the 32-byte HS256 minimum;
nothing here is a real credential, and `.env` stays untracked.

## A note on scope

Simulated results overstate real ones — always. This repository is an engineering
exercise, not investment advice, and nothing here should be treated as a reason to
trust a system with actual money.
