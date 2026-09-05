# Architecture

## The rule everything else follows

**The LLM proposes. A deterministic risk engine disposes.**

The language model never touches the broker. It emits a schema-validated *intent*
— instrument, direction, conviction, rationale — and that intent passes through a
hard-coded risk gate that can only shrink or reject it, never expand it.

Three consequences:

1. **The system must work with the LLM switched off.** Phase 03 ships a purely
   rule-based agent. If it can't behave sanely without a model, adding one won't
   rescue it.
2. **Every decision is replayable.** Each tick persists its input snapshot, the
   proposed intent, the gate's verdict and the resulting order.
3. **The kill switch is not in the agent.** It lives in the gate and in the
   Telegram bot, so it works even when the agent loop is wedged.

## Services

| Band | Component | Responsibility |
| --- | --- | --- |
| Surfaces | Angular app | Onboarding, watchlist, targets, decision audit log |
| Surfaces | Telegram bot | Push alerts and two-way commands — the primary interface |
| Edge | FastAPI gateway | Auth, REST, SSE stream, rate limiting |
| Brain | Agent orchestrator | The eight-stage loop; owns a run's lifecycle |
| Brain | Signal engine | Deterministic indicators. Pure functions, no I/O |
| Brain | LLM reasoner | Optional. Structured output only |
| Control | **Risk gate** | Non-bypassable. Caps, breakers, idempotency, halt state |
| Execution | Broker port | One interface, swappable adapters |
| Execution | Simulated exchange | Matching engine + synthetic universe. Default |
| Data | Market data service | Provider-agnostic ingestion, normalised |
| Data | Postgres + TimescaleDB | Relational state and time-series bars |
| Data | Redis | Hot quotes, pub/sub, locks, queue |
| Ops | Observability | Structured logs, metrics, dashboards, DLQ |

## The agent loop

One tick is one pass through eight stages. Ticks fire on a schedule (open, every
15 minutes, close) and on events (price breach, news on a held name, drawdown
threshold).

1. **Perceive** — fresh bars, quotes, news, corporate events
2. **Enrich** — indicators, volatility, position age, distance to target
3. **Recall** — policy, open orders, recent decisions on this name
4. **Reason** — rules produce candidates; LLM ranks them into a typed intent
5. **Gate** — validate, resize or reject; rejections logged with a reason code
6. **Execute** — bracket orders with an idempotency key, stops attached at entry
7. **Observe** — poll fills, reconcile against broker truth, detect drift
8. **Report** — persist the trace, notify by severity, update the stream

Every tick is idempotent. A crashed tick resumes; it never double-trades.

## Risk gate order

Schema → freshness → session → buying power → position cap → concentration →
frequency → duplicate → drawdown → circuit breaker.

Position caps *shrink* an order rather than rejecting it. Everything else rejects.

`SYSTEM_CEILINGS` in `app/models/policy.py` bounds what any user policy may allow.
A user can be stricter than the ceiling; never looser.

## Simulated exchange

Two modes behind one interface:

- **Replay** — real historical bars through the agent's clock. Real gaps, real
  crashes, known answers. Ideal for regression tests.
- **Synthetic** — a generated market: companies, sectors, fundamentals, news.
  Offline, endless, and seeded, so any bug is reproducible from its seed alone.

Build it adversarial, not convenient: widening spreads, partial fills, queue
position, simulated latency, realistic rejections, and a chaos flag that injects
slippage spikes, dropped fills and duplicate fill events.

## Reality checks

- Free market data shapes the strategy. Alpaca's free tier is IEX-only, 200
  req/min, and withholds the last 15 minutes — fine for swing horizons, wrong for
  intraday.
- The LLM is not where an edge comes from. It synthesises context and explains
  decisions. Discipline and risk management are what actually matter.
- Simulated results overstate real ones. Always. No market impact, no borrow
  costs, perfect data.
- Overfitting is the default outcome. Be most suspicious of good results that
  arrive right after you tuned something.
