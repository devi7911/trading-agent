# Agentic Trading Desk

An autonomous trading agent. You set targets and a watchlist once; the agent
handles research, sizing, entries, exits and reporting, and talks to you through
notifications rather than screens.

**Execution is simulated. There is no live trading adapter in this repository and
there is not meant to be one.**

The full architecture and the ten-phase plan live in [`docs/`](./docs/).

---

## Where this is

**Phase 00 — foundation.** Auth, database, migrations, Redis, health checks, and an
Angular shell with sign-up / sign-in. No agent, no market data, no orders yet.

| Phase | What | Status |
| ----- | ---- | ------ |
| 00 | Foundation: compose, schema, auth, health | ✅ done |
| 01 | Market data spine: synthetic universe + replay | next |
| 02 | Simulated exchange: matching engine, order lifecycle | |
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

### Phase 00 acceptance

1. `docker compose up` finishes with four healthy containers.
2. `GET /api/v1/health/ready` returns `{"status":"ok"}` with Postgres and Redis both `ok`.
3. You can create an account at http://localhost:4200/signup and land on the dashboard.
4. `docker compose exec api pytest` passes.

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
