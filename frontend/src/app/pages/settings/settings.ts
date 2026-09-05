import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';

import { MarketService } from '../../core/market.service';
import { TradingService } from '../../core/trading.service';
import {
  Instrument,
  NotificationRow,
  Policy,
  PolicyUpdate,
  TelegramStatus,
  WatchlistRow,
} from '../../core/models';
import { money } from '../../shared/format';

/** Named fields rather than an index signature: `Record<string, number>` makes
 *  every template access a bracketed lookup, which TypeScript rejects. */
interface PolicyDraft {
  max_position_pct: number;
  max_sector_pct: number;
  cash_floor_pct: number;
  stop_loss_pct: number;
  take_profit_pct: number;
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  max_trades_per_day: number;
}

const EMPTY_DRAFT: PolicyDraft = {
  max_position_pct: 10,
  max_sector_pct: 30,
  cash_floor_pct: 10,
  stop_loss_pct: 8,
  take_profit_pct: 20,
  max_daily_loss_pct: 3,
  max_drawdown_pct: 15,
  max_trades_per_day: 10,
};

const RUNGS = [
  {
    key: 'observe',
    label: 'Observe',
    detail: 'Logs what it would do. Places nothing. Start here.',
  },
  {
    key: 'approve',
    label: 'Approve each',
    detail: 'Every trade waits for you to say yes.',
  },
  {
    key: 'auto_capped',
    label: 'Auto within caps',
    detail: 'Small trades go through; larger ones still ask.',
  },
  {
    key: 'full_auto',
    label: 'Full auto',
    detail: 'Everything executes inside the risk envelope.',
  },
];

@Component({
  selector: 'app-settings',
  imports: [FormsModule],
  styles: [
    `
      /* A <button> resets the display of its children and the global button rule
         paints it with the accent colour, so the ladder needs both undone: the
         labels ran together on one line and every rung looked selected. */
      /* A ladder reads better as stacked rungs at full width than as four
         narrow columns with the detail text cramped. */
      .ladder {
        grid-template-columns: 1fr;
        gap: 8px;
      }
      .rung--button {
        display: flex;
        flex-direction: column;
        gap: 3px;
        text-align: left;
        font: inherit;
        cursor: pointer;
        background: var(--surface);
        border: 1px solid var(--line);
        color: var(--ink);
        padding: 14px 16px;
      }
      .rung--button:hover {
        border-color: var(--accent);
      }
      .rung--button.here {
        background: var(--accent-soft);
        border-color: var(--accent);
      }
      .rung--button .rl,
      .rung--button .rt,
      .rung--button .rx {
        display: block;
      }
    `,
  ],
  template: `
    <main class="page">
      @if (error()) { <div class="alert" role="alert">{{ error() }}</div> }
      @if (saved()) {
        <div class="alert" style="border-color:var(--gain);color:var(--gain)" role="status">
          {{ saved() }}
        </div>
      }

      <div class="page__head">
        <div>
          <h1 style="margin-bottom:4px">Settings</h1>
          <p class="muted" style="margin:0">
            How much rope the agent gets, and how it reaches you
          </p>
        </div>
        @if (policy(); as p) {
          <span class="muted mono">policy v{{ p.version }}</span>
        }
      </div>

      <!-- autonomy -->
      <section class="panel" style="margin-bottom:14px">
        <div class="panel__head">
          <h2 class="panel__title">Autonomy</h2>
          <span class="muted" style="font-size:.8rem">Promote one rung at a time</span>
        </div>
        <div class="panel__body">
          <div class="ladder">
            @for (r of rungs; track r.key) {
              <button
                type="button"
                class="rung rung--button"
                [class.here]="policy()?.autonomy_level === r.key"
                [attr.aria-pressed]="policy()?.autonomy_level === r.key"
                (click)="setAutonomy(r.key)"
              >
                <span class="rl">Level {{ $index }}</span>
                <span class="rt">{{ r.label }}</span>
                <span class="rx">{{ r.detail }}</span>
              </button>
            }
          </div>
        </div>
      </section>

      <!-- risk limits -->
      @if (policy(); as p) {
        <section class="panel" style="margin-bottom:14px">
          <div class="panel__head">
            <h2 class="panel__title">Risk limits</h2>
            <span class="muted" style="font-size:.8rem">
              Saving writes a new policy version
            </span>
          </div>
          <div class="panel__body">
            <div class="grid grid--split">
              <div>
                <div class="field">
                  <label for="pos">Max in one name (% of equity)</label>
                  <input id="pos" type="number" min="0.1" max="25" step="0.5"
                         [(ngModel)]="draft.max_position_pct" />
                  <span class="hint">System ceiling is 25%, whatever you set here.</span>
                </div>
                <div class="field">
                  <label for="sector">Max in one sector (%)</label>
                  <input id="sector" type="number" min="1" max="50" step="1"
                         [(ngModel)]="draft.max_sector_pct" />
                </div>
                <div class="field">
                  <label for="cash">Cash floor (%)</label>
                  <input id="cash" type="number" min="0" max="90" step="1"
                         [(ngModel)]="draft.cash_floor_pct" />
                  <span class="hint">The agent is never allowed to be fully invested.</span>
                </div>
                <div class="field">
                  <label for="trades">Max trades per day</label>
                  <input id="trades" type="number" min="1" max="50" step="1"
                         [(ngModel)]="draft.max_trades_per_day" />
                </div>
              </div>
              <div>
                <div class="field">
                  <label for="stop">Stop loss (%)</label>
                  <input id="stop" type="number" min="1" max="50" step="0.5"
                         [(ngModel)]="draft.stop_loss_pct" />
                </div>
                <div class="field">
                  <label for="take">Take profit (%)</label>
                  <input id="take" type="number" min="1" max="200" step="1"
                         [(ngModel)]="draft.take_profit_pct" />
                </div>
                <div class="field">
                  <label for="daily">Daily loss limit (%)</label>
                  <input id="daily" type="number" min="0.5" max="10" step="0.5"
                         [(ngModel)]="draft.max_daily_loss_pct" />
                  <span class="hint">Breaching this halts new entries for the day.</span>
                </div>
                <div class="field">
                  <label for="dd">Max drawdown (%)</label>
                  <input id="dd" type="number" min="1" max="30" step="1"
                         [(ngModel)]="draft.max_drawdown_pct" />
                </div>
              </div>
            </div>
            <button type="button" [disabled]="busy()" (click)="savePolicy()">
              {{ busy() ? 'Saving…' : 'Save limits' }}
            </button>
          </div>
        </section>
      }

      <!-- watchlist -->
      <section class="panel" style="margin-bottom:14px">
        <div class="panel__head">
          <h2 class="panel__title">Watchlist</h2>
          <span class="muted mono">{{ watchlist().length }} symbols</span>
        </div>
        <div class="panel__body">
          <div class="toolbar" style="margin-bottom:12px">
            <input
              class="search"
              type="text"
              placeholder="Add a symbol…"
              [(ngModel)]="symbolToAdd"
              (keyup.enter)="add()"
              list="instrument-options"
            />
            <datalist id="instrument-options">
              @for (i of allInstruments(); track i.id) {
                <option [value]="i.symbol">{{ i.name }}</option>
              }
            </datalist>
            <button class="chip" type="button" (click)="add()">Add</button>
          </div>
          <div class="tablewrap">
            <table class="data">
              <thead>
                <tr>
                  <th>Symbol</th><th>Name</th><th>Sector</th>
                  <th class="num">Last</th><th>Conviction</th><th></th>
                </tr>
              </thead>
              <tbody>
                @for (w of watchlist(); track w.id) {
                  <tr>
                    <td class="sym">{{ w.symbol }}</td>
                    <td class="muted">{{ w.name }}</td>
                    <td class="muted">{{ w.sector }}</td>
                    <td class="num">{{ fmtMoney(w.last_price) }}</td>
                    <td>
                      <div class="toolbar">
                        @for (tier of [1, 2, 3]; track tier) {
                          <button
                            class="chip"
                            type="button"
                            [class.active]="w.conviction === tier"
                            (click)="setConviction(w, tier)"
                          >
                            {{ tier }}
                          </button>
                        }
                      </div>
                    </td>
                    <td>
                      <button class="chip" type="button" (click)="remove(w)">Remove</button>
                    </td>
                  </tr>
                } @empty {
                  <tr>
                    <td colspan="6" class="muted">
                      Empty. The agent only considers symbols on this list plus anything
                      it already holds.
                    </td>
                  </tr>
                }
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <!-- notifications -->
      <div class="grid grid--split">
        <section class="panel">
          <div class="panel__head"><h2 class="panel__title">Telegram</h2></div>
          <div class="panel__body">
            @if (telegram(); as t) {
              @if (!t.bot_configured) {
                <p class="muted">
                  No bot token is configured. Create a bot with @BotFather in Telegram, put
                  the token in <code>.env</code> as <code>TELEGRAM_BOT_TOKEN</code>, and
                  restart. Until then notifications are recorded here but not pushed.
                </p>
              } @else if (t.linked) {
                <p><span class="pill ok">Linked</span></p>
                <p class="muted">
                  You will get trades, stops, targets and circuit breakers as they happen,
                  plus a daily summary.
                </p>
              } @else {
                <p class="muted">Not linked yet.</p>
                <button type="button" (click)="link()">Get a link code</button>
                @if (linkCode()) {
                  <p class="mono" style="margin-top:12px">{{ linkCode() }}</p>
                }
              }
            } @else {
              <p class="muted">Checking…</p>
            }
          </div>
        </section>

        <section class="panel">
          <div class="panel__head">
            <h2 class="panel__title">Recent notifications</h2>
          </div>
          <div class="panel__body panel__body--flush">
            @for (n of notifications(); track $index) {
              <article class="news-item">
                <span class="news-item__dot" [class]="severityClass(n)"></span>
                <div>
                  <div class="news-item__headline">{{ n.title }}</div>
                  <div class="news-item__meta">
                    {{ n.at.slice(5, 16).replace('T', ' ') }} · {{ n.severity }} ·
                    {{ n.status }}{{ n.error ? ' — ' + n.error : '' }}
                  </div>
                </div>
              </article>
            } @empty {
              <p class="muted" style="padding:16px">Nothing yet.</p>
            }
          </div>
        </section>
      </div>
    </main>
  `,
})
export class SettingsPage implements OnInit {
  private readonly trading = inject(TradingService);
  private readonly market = inject(MarketService);

  readonly rungs = RUNGS;
  readonly policy = signal<Policy | null>(null);
  readonly watchlist = signal<WatchlistRow[]>([]);
  readonly allInstruments = signal<Instrument[]>([]);
  readonly telegram = signal<TelegramStatus | null>(null);
  readonly notifications = signal<NotificationRow[]>([]);
  readonly linkCode = signal<string | null>(null);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly saved = signal<string | null>(null);

  symbolToAdd = '';
  draft: PolicyDraft = { ...EMPTY_DRAFT };

  readonly fmtMoney = money;

  ngOnInit(): void {
    this.loadPolicy();
    this.loadWatchlist();
    this.market.instruments().subscribe({ next: (i) => this.allInstruments.set(i) });
    this.trading.telegram().subscribe({ next: (t) => this.telegram.set(t) });
    this.trading.notifications().subscribe({ next: (n) => this.notifications.set(n) });
  }

  private loadPolicy(): void {
    this.trading.policy().subscribe({
      next: (p) => {
        this.policy.set(p);
        this.draft = {
          max_position_pct: parseFloat(p.max_position_pct),
          max_sector_pct: parseFloat(p.max_sector_pct),
          cash_floor_pct: parseFloat(p.cash_floor_pct),
          stop_loss_pct: parseFloat(p.stop_loss_pct),
          take_profit_pct: parseFloat(p.take_profit_pct),
          max_daily_loss_pct: parseFloat(p.max_daily_loss_pct),
          max_drawdown_pct: parseFloat(p.max_drawdown_pct),
          max_trades_per_day: p.max_trades_per_day,
        };
      },
      error: (err) => this.error.set(err?.error?.detail ?? 'Could not load the policy.'),
    });
  }

  private loadWatchlist(): void {
    this.trading.watchlist().subscribe({ next: (w) => this.watchlist.set(w) });
  }

  setAutonomy(level: string): void {
    this.trading.updatePolicy({ autonomy_level: level }).subscribe({
      next: (p) => {
        this.policy.set(p);
        this.saved.set(`Autonomy set to ${level.replace('_', ' ')} (policy v${p.version}).`);
      },
      error: (err) => this.error.set(err?.error?.detail ?? 'Could not change autonomy.'),
    });
  }

  savePolicy(): void {
    this.busy.set(true);
    this.trading.updatePolicy(this.draft as unknown as PolicyUpdate).subscribe({
      next: (p) => {
        this.busy.set(false);
        this.policy.set(p);
        this.saved.set(`Limits saved as policy v${p.version}.`);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(err?.error?.detail ?? 'Could not save the limits.');
      },
    });
  }

  add(): void {
    const symbol = this.symbolToAdd.trim().toUpperCase();
    if (!symbol) return;
    this.trading.addToWatchlist(symbol).subscribe({
      next: () => {
        this.symbolToAdd = '';
        this.loadWatchlist();
      },
      error: (err) => this.error.set(err?.error?.detail ?? `Could not add ${symbol}.`),
    });
  }

  setConviction(row: WatchlistRow, tier: number): void {
    if (!row.symbol) return;
    this.trading.addToWatchlist(row.symbol, tier).subscribe({ next: () => this.loadWatchlist() });
  }

  remove(row: WatchlistRow): void {
    if (!row.symbol) return;
    this.trading.removeFromWatchlist(row.symbol).subscribe({ next: () => this.loadWatchlist() });
  }

  link(): void {
    this.trading.linkTelegram().subscribe({
      next: (r) => this.linkCode.set(r.instructions),
      error: () => this.error.set('Could not generate a link code.'),
    });
  }

  severityClass(n: NotificationRow): string {
    if (n.status === 'failed') return 'neg';
    if (n.severity === 'immediate') return 'pos';
    return '';
  }
}
