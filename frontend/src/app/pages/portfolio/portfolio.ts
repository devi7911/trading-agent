import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { RouterLink } from '@angular/router';

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
  template: `
    <main class="page">
      @if (error()) {
        <div class="alert" role="alert">{{ error() }}</div>
      }

      <div class="page__head">
        <div>
          <h1 style="margin-bottom:4px">Portfolio</h1>
          <p class="muted" style="margin:0">Simulated account · nothing here is real money</p>
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
            <div class="tile__value">{{ fmtMoney(a.equity) }}</div>
            <div class="tile__sub" [class]="tone(a.total_return_pct)">
              {{ fmtPct(a.total_return_pct ?? 0) }} since inception
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Cash</div>
            <div class="tile__value">{{ fmtMoney(a.cash) }}</div>
            <div class="tile__sub">{{ cashPct(a).toFixed(0) }}% of equity</div>
          </div>
          <div class="tile">
            <div class="tile__label">Invested</div>
            <div class="tile__value">{{ fmtMoney(invested()) }}</div>
            <div class="tile__sub">{{ a.open_positions }} positions</div>
          </div>
          <div class="tile">
            <div class="tile__label">Unrealised</div>
            <div class="tile__value" [class]="tone(unrealised())">
              {{ fmtMoney(unrealised()) }}
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
                    <td class="num">{{ fmtMoney(p.last_price) }}</td>
                    <td class="num">{{ fmtMoney(p.market_value) }}</td>
                    <td class="num" [class]="tone(num(p.unrealised_pnl))">
                      {{ fmtMoney(p.unrealised_pnl) }}
                    </td>
                    <td class="num" [class]="tone(p.unrealised_pct)">
                      {{ fmtPct(p.unrealised_pct ?? 0, 1) }}
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

  readonly account = signal<TradingAccount | null>(null);
  readonly positions = signal<PositionRow[]>([]);
  readonly orders = signal<OrderRow[]>([]);
  readonly reconciliation = signal<Reconciliation | null>(null);
  readonly error = signal<string | null>(null);

  readonly invested = computed(() =>
    this.positions().reduce((sum, p) => sum + this.num(p.market_value), 0),
  );
  readonly unrealised = computed(() =>
    this.positions().reduce((sum, p) => sum + this.num(p.unrealised_pnl), 0),
  );
  readonly realised = computed(() =>
    this.positions().reduce((sum, p) => sum + this.num(p.realised_pnl), 0),
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

  num(value: string | number | null | undefined): number {
    if (value === null || value === undefined) return 0;
    return typeof value === 'string' ? parseFloat(value) : value;
  }

  cashPct(a: TradingAccount): number {
    const equity = this.num(a.equity);
    return equity ? (this.num(a.cash) / equity) * 100 : 0;
  }

  statusClass(status: string): string {
    if (status === 'filled') return 'pill ok';
    if (status === 'rejected' || status === 'expired') return 'pill down';
    return 'pill degraded';
  }
}
