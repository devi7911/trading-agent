import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

import { LiveService } from '../../core/live.service';
import { TradingService } from '../../core/trading.service';
import {
  OrderRow,
  PositionRow,
  Reconciliation,
  TradingAccount,
} from '../../core/models';
import { compact, money, pct, toneClass } from '../../shared/format';

@Component({
  selector: 'app-portfolio',
  imports: [RouterLink],
  styles: [
    `
      /* A brief tint when a price changes, so movement is noticeable without
         the table becoming a light show. */
      .flash {
        animation: flash 700ms ease-out;
      }
      @keyframes flash {
        from { background: var(--accent-soft); }
        to { background: transparent; }
      }
      @media (prefers-reduced-motion: reduce) {
        .flash { animation: none; }
      }
    `,
  ],
  template: `
    <main class="page">
      @if (error()) {
        <div class="alert" role="alert">{{ error() }}</div>
      }

      <div class="page__head">
        <div>
          <h1 style="margin-bottom:4px">Portfolio</h1>
          <p class="muted" style="margin:0">
            Simulated account · nothing here is real money
            @if (live.connected()) {
              <span class="gain"> · prices are live</span>
            }
          </p>
        </div>
        @if (account(); as a) {
          @if (a.is_halted) {
            <span class="regime bear">Halted — {{ a.halt_reason }}</span>
          }
        }
      </div>

      @if (account(); as a) {
        <div class="grid grid--tiles" style="margin-bottom:14px">
          <div class="tile">
            <div class="tile__label">Equity</div>
            <div class="tile__value">{{ fmtMoney(liveEquity(a)) }}</div>
            <div class="tile__sub" [class]="tone(liveReturnPct(a))">
              {{ fmtPct(liveReturnPct(a)) }} since inception
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Cash</div>
            <div class="tile__value">{{ fmtMoney(a.cash) }}</div>
            <div class="tile__sub">{{ cashPct(a).toFixed(0) }}% of equity</div>
          </div>
          <div class="tile">
            <div class="tile__label">Invested</div>
            <div class="tile__value">{{ fmtMoney(liveInvested()) }}</div>
            <div class="tile__sub">{{ a.open_positions }} positions</div>
          </div>
          <div class="tile">
            <div class="tile__label">Unrealised</div>
            <div class="tile__value" [class]="tone(liveUnrealisedTotal())">
              {{ fmtMoney(liveUnrealisedTotal()) }}
            </div>
            <div class="tile__sub">open positions</div>
          </div>
          <div class="tile">
            <div class="tile__label">Realised</div>
            <div class="tile__value" [class]="tone(realised())">
              {{ fmtMoney(realised()) }}
            </div>
            <div class="tile__sub">closed trades</div>
          </div>
          <div class="tile">
            <div class="tile__label">Ledger</div>
            @if (reconciliation(); as r) {
              <div class="tile__value" [class]="r.reconciled ? 'gain' : 'loss'">
                {{ r.reconciled ? 'Reconciled' : 'DRIFT' }}
              </div>
              <div class="tile__sub">
                {{ r.reconciled ? 'matches the fill history' : 'differs by ' + r.cash_difference }}
              </div>
            } @else {
              <div class="tile__value muted">…</div>
            }
          </div>
        </div>

        <section class="panel" style="margin-bottom:14px">
          <div class="panel__head">
            <h2 class="panel__title">Positions</h2>
            <span class="muted mono">{{ positions().length }} open</span>
          </div>
          <div class="panel__body panel__body--flush tablewrap">
            <table class="data">
              <thead>
                <tr>
                  <th>Symbol</th>
                  <th class="num">Qty</th>
                  <th class="num">Avg cost</th>
                  <th class="num">Last</th>
                  <th class="num">Value</th>
                  <th class="num">Unrealised</th>
                  <th class="num">%</th>
                  <th class="num">Realised</th>
                </tr>
              </thead>
              <tbody>
                @for (p of positions(); track p.id) {
                  <tr>
                    <td class="sym">
                      <a [routerLink]="['/instrument', p.symbol]">{{ p.symbol }}</a>
                    </td>
                    <td class="num">{{ p.quantity }}</td>
                    <td class="num">{{ fmtMoney(p.avg_cost) }}</td>
                    <td
                      class="num"
                      [class.flash]="live.changed().has(p.symbol ?? '')"
                    >
                      {{ fmtMoney(livePrice(p)) }}
                    </td>
                    <td class="num">{{ fmtMoney(liveValue(p)) }}</td>
                    <td class="num" [class]="tone(liveUnrealised(p))">
                      {{ fmtMoney(liveUnrealised(p)) }}
                    </td>
                    <td class="num" [class]="tone(liveUnrealisedPct(p))">
                      {{ fmtPct(liveUnrealisedPct(p), 1) }}
                    </td>
                    <td class="num" [class]="tone(num(p.realised_pnl))">
                      {{ fmtMoney(p.realised_pnl) }}
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="8" class="muted">
                      No open positions. The agent opens them on its next tick.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </section>

        <section class="panel">
          <div class="panel__head">
            <h2 class="panel__title">Order blotter</h2>
            <span class="muted mono">{{ orders().length }} most recent</span>
          </div>
          <div class="panel__body panel__body--flush tablewrap">
            <table class="data">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Symbol</th>
                  <th>Side</th>
                  <th class="num">Qty</th>
                  <th class="num">Filled</th>
                  <th class="num">Price</th>
                  <th>Status</th>
                  <th>Why</th>
                </tr>
              </thead>
              <tbody>
                @for (o of orders(); track o.id) {
                  <tr>
                    <td class="muted mono">{{ o.created_at.slice(5, 16).replace('T', ' ') }}</td>
                    <td class="sym">{{ o.symbol }}</td>
                    <td [class]="o.side === 'buy' ? 'gain' : 'loss'">{{ o.side }}</td>
                    <td class="num">{{ o.quantity }}</td>
                    <td class="num">{{ o.filled_quantity }}</td>
                    <td class="num">{{ fmtMoney(o.avg_fill_price) }}</td>
                    <td>
                      <span class="pill" [class]="statusClass(o.status)">{{ o.status }}</span>
                    </td>
                    <td class="muted" style="white-space:normal;max-width:320px">
                      {{ o.reject_reason || o.note || '—' }}
                    </td>
                  </tr>
                } @empty {
                  <tr><td colspan="8" class="muted">No orders yet.</td></tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      } @else if (!error()) {
        <p class="spinner">Loading portfolio…</p>
      }
    </main>
  `,
})
export class PortfolioPage implements OnInit {
  private readonly trading = inject(TradingService);
  readonly live = inject(LiveService);

  readonly account = signal<TradingAccount | null>(null);
  readonly positions = signal<PositionRow[]>([]);
  readonly orders = signal<OrderRow[]>([]);
  readonly reconciliation = signal<Reconciliation | null>(null);
  readonly error = signal<string | null>(null);

  readonly realised = computed(() =>
    this.positions().reduce((sum, p) => sum + this.num(p.realised_pnl), 0),
  );

  /** Position value at the live price, falling back to the last stored close. */
  readonly liveInvested = computed(() =>
    this.positions().reduce((sum, p) => sum + this.liveValue(p), 0),
  );
  readonly liveUnrealisedTotal = computed(() =>
    this.positions().reduce((sum, p) => sum + this.liveUnrealised(p), 0),
  );

  readonly fmtPct = pct;
  readonly fmtMoney = money;
  readonly fmtCompact = compact;
  readonly tone = toneClass;

  ngOnInit(): void {
    this.trading.account().subscribe({
      next: (a) => this.account.set(a),
      error: (err) =>
        this.error.set(err?.error?.detail ?? 'Could not load the account.'),
    });
    this.trading.positions().subscribe({ next: (p) => this.positions.set(p) });
    this.trading.orders().subscribe({ next: (o) => this.orders.set(o) });
    this.trading.reconcile().subscribe({ next: (r) => this.reconciliation.set(r) });
  }

  /** The live price if the stream has one, otherwise the stored close. */
  livePrice(p: PositionRow): number {
    return this.live.price(p.symbol) ?? this.num(p.last_price);
  }

  liveValue(p: PositionRow): number {
    return this.livePrice(p) * p.quantity;
  }

  liveUnrealised(p: PositionRow): number {
    return (this.livePrice(p) - this.num(p.avg_cost)) * p.quantity;
  }

  liveUnrealisedPct(p: PositionRow): number {
    const cost = this.num(p.avg_cost);
    return cost ? (this.livePrice(p) / cost - 1) * 100 : 0;
  }

  /** Equity revalued in the browser: cash never changes between ticks, only
   *  the market value of what is held. */
  liveEquity(a: TradingAccount): number {
    return this.num(a.cash) + this.liveInvested();
  }

  liveReturnPct(a: TradingAccount): number {
    const start = this.num(a.starting_cash);
    return start ? (this.liveEquity(a) / start - 1) * 100 : 0;
  }

  num(value: string | number | null | undefined): number {
    if (value === null || value === undefined) return 0;
    return typeof value === 'string' ? parseFloat(value) : value;
  }

  cashPct(a: TradingAccount): number {
    const equity = this.liveEquity(a);
    return equity ? (this.num(a.cash) / equity) * 100 : 0;
  }

  statusClass(status: string): string {
    if (status === 'filled') return 'pill ok';
    if (status === 'rejected' || status === 'expired') return 'pill down';
    return 'pill degraded';
  }
}
