import { Component, OnInit, inject, signal } from '@angular/core';

import { TradingService } from '../../core/trading.service';
import { AgentRunRow, DecisionRow, RiskCheck } from '../../core/models';
import { pct, toneClass } from '../../shared/format';

@Component({
  selector: 'app-agent',
  template: `
    <main class="page">
      @if (error()) {
        <div class="alert" role="alert">{{ error() }}</div>
      }
      @if (notice()) {
        <div class="alert" style="border-color:var(--accent);color:var(--accent)" role="status">
          {{ notice() }}
        </div>
      }

      <div class="page__head">
        <div>
          <h1 style="margin-bottom:4px">Agent</h1>
          <p class="muted" style="margin:0">
            Every decision it made, and why — including the ones where it did nothing
          </p>
        </div>
        <div class="toolbar">
          <button class="chip" type="button" [disabled]="busy()" (click)="tick(true)">
            Dry run
          </button>
          <button class="chip" type="button" [disabled]="busy()" (click)="tick(false)">
            Run a tick now
          </button>
          @if (halted()) {
            <button type="button" (click)="setHalt(false)">Resume</button>
          } @else {
            <button
              type="button"
              style="background:var(--loss)"
              (click)="setHalt(true)"
            >
              Halt trading
            </button>
          }
        </div>
      </div>

      @if (halted()) {
        <div class="callout-halt">
          Trading is halted. The agent still evaluates and records every decision, but no
          orders will be placed until you resume.
        </div>
      }

      <section class="panel" style="margin-bottom:14px">
        <div class="panel__head">
          <h2 class="panel__title">Recent ticks</h2>
          <span class="muted mono">{{ runs().length }} shown</span>
        </div>
        <div class="panel__body panel__body--flush tablewrap">
          <table class="data">
            <thead>
              <tr>
                <th>Started</th>
                <th>Trigger</th>
                <th>Status</th>
                <th class="num">Symbols</th>
                <th class="num">Intents</th>
                <th class="num">Orders</th>
                <th class="num">Declined</th>
                <th class="num">Took</th>
              </tr>
            </thead>
            <tbody>
              @for (r of runs(); track r.id) {
                <tr
                  (click)="openRun(r)"
                  style="cursor:pointer"
                  [style.background]="selectedRun() === r.id ? 'var(--accent-soft)' : ''"
                >
                  <td class="mono muted">{{ r.started_at.slice(5, 16).replace('T', ' ') }}</td>
                  <td class="muted">{{ r.trigger }}</td>
                  <td>
                    <span class="pill" [class]="runClass(r)">{{ r.status }}</span>
                  </td>
                  <td class="num">{{ r.symbols_examined }}</td>
                  <td class="num">{{ r.intents_formed }}</td>
                  <td class="num" [class]="r.orders_placed ? 'gain' : ''">
                    {{ r.orders_placed }}
                  </td>
                  <td class="num muted">{{ r.denials }}</td>
                  <td class="num muted">{{ r.duration_ms }}ms</td>
                </tr>
              } @empty {
                <tr>
                  <td colspan="8" class="muted">
                    No ticks yet. The worker runs every 15 minutes, or use “Run a tick now”.
                  </td>
                </tr>
              }
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel__head">
          <h2 class="panel__title">
            {{ selectedRun() ? 'Decisions in this tick' : 'Decision log' }}
          </h2>
          @if (selectedRun()) {
            <button class="chip" type="button" (click)="clearRun()">Show all recent</button>
          }
        </div>
        <div class="panel__body panel__body--flush">
          @for (d of decisions(); track $index) {
            <article class="decision">
              <div class="decision__head" (click)="toggle($index)">
                <span class="decision__sym">{{ d.symbol }}</span>
                <span
                  class="pill"
                  [class]="d.approved ? 'pill ok' : (d.denial ? 'pill down' : 'pill degraded')"
                >
                  {{ d.approved ? d.direction + ' ' + quantity(d) : (d.denial || 'hold') }}
                </span>
                <span class="muted mono decision__conviction">
                  conviction {{ d.conviction.toFixed(2) }}
                </span>
                <span class="decision__reason">{{ d.rationale }}</span>
                <span class="muted mono">{{ expanded() === $index ? '▾' : '▸' }}</span>
              </div>

              @if (expanded() === $index && d.risk_trace?.checks?.length) {
                <div class="decision__trace">
                  <div class="muted mono decision__tracehead">Risk gate</div>
                  @for (c of d.risk_trace!.checks!; track c.check) {
                    <div class="check">
                      <span class="check__mark" [class]="c.passed ? 'gain' : 'loss'">
                        {{ c.passed ? '✓' : '✕' }}
                      </span>
                      <span class="check__name mono">{{ c.check }}</span>
                      <span class="check__detail muted">{{ c.detail }}</span>
                      @if (c.adjusted_quantity !== null) {
                        <span class="pill degraded">reduced to {{ c.adjusted_quantity }}</span>
                      }
                    </div>
                  }
                </div>
              }
            </article>
          } @empty {
            <p class="muted" style="padding:16px">No decisions recorded yet.</p>
          }
        </div>
      </section>
    </main>
  `,
  styles: [
    `
      .callout-halt {
        border: 1px solid var(--loss);
        border-radius: var(--radius);
        background: color-mix(in srgb, var(--loss) 8%, transparent);
        color: var(--loss);
        padding: 12px 16px;
        font-size: 0.9rem;
        margin-bottom: 14px;
      }
      .decision {
        border-bottom: 1px solid var(--line);
      }
      .decision:last-child {
        border-bottom: 0;
      }
      .decision__head {
        display: grid;
        grid-template-columns: 68px 130px 120px 1fr 20px;
        gap: 12px;
        align-items: center;
        padding: 10px 16px;
        cursor: pointer;
        font-size: 0.86rem;
      }
      .decision__head:hover {
        background: var(--surface-2);
      }
      .decision__sym {
        font-weight: 600;
      }
      .decision__conviction {
        font-size: 0.75rem;
      }
      .decision__reason {
        color: var(--ink-2);
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .decision__trace {
        padding: 4px 16px 14px 16px;
        background: var(--surface-2);
      }
      .decision__tracehead {
        font-size: 0.68rem;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        padding: 8px 0 6px;
      }
      .check {
        display: grid;
        grid-template-columns: 16px 130px 1fr auto;
        gap: 10px;
        align-items: baseline;
        font-size: 0.82rem;
        padding: 3px 0;
      }
      .check__name {
        font-size: 0.76rem;
      }
      .check__detail {
        line-height: 1.45;
      }
      @media (max-width: 760px) {
        .decision__head {
          grid-template-columns: 60px 1fr 20px;
        }
        .decision__conviction,
        .decision__reason {
          display: none;
        }
        .check {
          grid-template-columns: 16px 1fr;
        }
        .check__detail {
          grid-column: 1 / -1;
          padding-left: 26px;
        }
      }
    `,
  ],
})
export class AgentPage implements OnInit {
  private readonly trading = inject(TradingService);

  readonly runs = signal<AgentRunRow[]>([]);
  readonly decisions = signal<DecisionRow[]>([]);
  readonly selectedRun = signal<string | null>(null);
  readonly expanded = signal<number | null>(null);
  readonly halted = signal(false);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly notice = signal<string | null>(null);

  readonly fmtPct = pct;
  readonly tone = toneClass;

  ngOnInit(): void {
    this.refresh();
  }

  refresh(): void {
    this.trading.runs().subscribe({
      next: (r) => this.runs.set(r),
      error: (err) => this.error.set(err?.error?.detail ?? 'Could not load agent runs.'),
    });
    this.trading.decisions().subscribe({ next: (d) => this.decisions.set(d) });
    this.trading.haltStatus().subscribe({ next: (h) => this.halted.set(h.halted) });
  }

  openRun(run: AgentRunRow): void {
    this.selectedRun.set(run.id);
    this.expanded.set(null);
    this.trading.runDecisions(run.id).subscribe({ next: (d) => this.decisions.set(d) });
  }

  clearRun(): void {
    this.selectedRun.set(null);
    this.expanded.set(null);
    this.trading.decisions().subscribe({ next: (d) => this.decisions.set(d) });
  }

  toggle(index: number): void {
    this.expanded.set(this.expanded() === index ? null : index);
  }

  quantity(d: DecisionRow): number {
    return d.approved_quantity ?? d.quantity ?? 0;
  }

  runClass(r: AgentRunRow): string {
    if (r.status === 'completed') return 'pill ok';
    if (r.status === 'failed') return 'pill down';
    return 'pill degraded';
  }

  tick(dryRun: boolean): void {
    this.busy.set(true);
    this.notice.set(null);
    this.trading.tick(dryRun).subscribe({
      next: (result) => {
        this.busy.set(false);
        const orders = result['orders_placed'];
        const denials = result['denials'];
        this.notice.set(
          dryRun
            ? `Dry run finished: ${result['intents_formed']} intents formed, nothing placed.`
            : `Tick finished: ${orders} order(s) placed, ${denials} declined.`,
        );
        this.refresh();
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(err?.error?.detail ?? 'The tick failed.');
      },
    });
  }

  setHalt(halt: boolean): void {
    const call = halt ? this.trading.setHalt() : this.trading.clearHalt();
    call.subscribe({
      next: () => {
        this.halted.set(halt);
        this.notice.set(halt ? 'Trading halted.' : 'Trading resumed.');
      },
      error: () => this.error.set('Could not change the halt state.'),
    });
  }
}
