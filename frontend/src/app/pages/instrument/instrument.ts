import {
  Component,
  ElementRef,
  Input,
  OnDestroy,
  OnInit,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { CandlestickSeries, HistogramSeries, createChart } from 'lightweight-charts';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';

import { MarketService } from '../../core/market.service';
import {
  Bar,
  CorporateEvent,
  Instrument,
  InstrumentStats,
  NewsItem,
} from '../../core/models';
import { chartOptions, onThemeChange, token } from '../../shared/chart-theme';
import { compact, money, pct, toChartDate, toneClass } from '../../shared/format';

const RANGES = [
  { key: 21, label: '1M' },
  { key: 63, label: '3M' },
  { key: 126, label: '6M' },
  { key: 252, label: '1Y' },
  { key: 0, label: 'All' },
];

@Component({
  selector: 'app-instrument',
  imports: [RouterLink],
  template: `
    <main class="page">
      @if (error()) {
        <div class="alert" role="alert">{{ error() }}</div>
      }

      <div class="page__head">
        <div>
          <p class="muted" style="margin:0 0 4px">
            <a routerLink="/market" style="text-decoration:none">← Market</a>
          </p>
          <h1 style="margin-bottom:4px">
            {{ symbol }}
            @if (instrument(); as i) {
              <span class="muted" style="font-weight:400;font-size:1.05rem"> · {{ i.name }}</span>
            }
          </h1>
          @if (instrument(); as i) {
            <p class="muted" style="margin:0">
              {{ i.sector }} · beta {{ i.beta }} · {{ fmtCompact(i.shares_outstanding) }} shares
            </p>
          }
        </div>

        <div style="text-align:right">
          @if (stats(); as s) {
            <div class="tile__value" style="font-size:1.9rem">{{ fmtMoney(s.last) }}</div>
            <div [class]="tone(s.period_return_pct)" style="font-weight:600">
              {{ fmtPct(s.period_return_pct) }} over {{ s.lookback_days }} sessions
            </div>
          }
        </div>
      </div>

      <section class="panel" style="margin-bottom:14px">
        <div class="panel__head">
          <div class="toolbar">
            @for (r of ranges; track r.key) {
              <button
                class="chip"
                type="button"
                [class.active]="range() === r.key"
                (click)="setRange(r.key)"
              >
                {{ r.label }}
              </button>
            }
          </div>
          <div class="toolbar">
            <button class="chip" type="button" (click)="download('bars.csv', symbol + '_bars.csv')">
              CSV
            </button>
            <button
              class="chip"
              type="button"
              (click)="download('tearsheet.pdf', symbol + '_tearsheet.pdf')"
            >
              PDF tearsheet
            </button>
          </div>
        </div>
        <div class="panel__body panel__body--flush">
          <div #priceChart class="chart"></div>
        </div>
      </section>

      @if (stats(); as s) {
        <div class="grid grid--tiles" style="margin-bottom:14px">
          <div class="tile">
            <div class="tile__label">Annualised return</div>
            <div class="tile__value" [class]="tone(s.annualised_return_pct)">
              {{ fmtPct(s.annualised_return_pct, 1) }}
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Annualised vol</div>
            <div class="tile__value">{{ s.annualised_vol_pct.toFixed(1) }}%</div>
          </div>
          <div class="tile">
            <div class="tile__label">Sharpe</div>
            <div class="tile__value">{{ s.sharpe ?? '—' }}</div>
            <div class="tile__sub">rf = 0</div>
          </div>
          <div class="tile">
            <div class="tile__label">Max drawdown</div>
            <div class="tile__value loss">{{ s.max_drawdown_pct.toFixed(1) }}%</div>
            <div class="tile__sub">now {{ s.current_drawdown_pct.toFixed(1) }}%</div>
          </div>
          <div class="tile">
            <div class="tile__label">Up days</div>
            <div class="tile__value">{{ s.up_day_pct }}%</div>
            <div class="tile__sub">
              best {{ fmtPct(s.best_day_pct, 1) }} · worst {{ fmtPct(s.worst_day_pct, 1) }}
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Avg volume</div>
            <div class="tile__value">{{ fmtCompact(s.avg_volume) }}</div>
          </div>
        </div>
      }

      <div class="grid grid--split">
        <section class="panel">
          <div class="panel__head"><h2 class="panel__title">Headlines</h2></div>
          <div class="panel__body panel__body--flush">
            @for (n of news(); track n.id) {
              <article class="news-item">
                <span class="news-item__dot" [class]="sentimentClass(n.sentiment)"></span>
                <div>
                  <div class="news-item__headline">{{ n.headline }}</div>
                  <div class="news-item__meta">
                    {{ n.published_at.slice(0, 10) }} · {{ n.category }} · {{ n.source }}
                  </div>
                </div>
              </article>
            } @empty {
              <p class="muted" style="padding:16px">No headlines.</p>
            }
          </div>
        </section>

        <section class="panel">
          <div class="panel__head"><h2 class="panel__title">Earnings history</h2></div>
          <div class="panel__body panel__body--flush tablewrap">
            <table class="data">
              <thead>
                <tr>
                  <th>Date</th>
                  <th class="num">Estimate</th>
                  <th class="num">Actual</th>
                  <th class="num">Surprise</th>
                </tr>
              </thead>
              <tbody>
                @for (e of earnings(); track e.id) {
                  <tr>
                    <td>{{ e.occurs_at.slice(0, 10) }}</td>
                    <td class="num">{{ fmtMoney(e.eps_estimate) }}</td>
                    <td class="num">{{ fmtMoney(e.eps_actual) }}</td>
                    <td class="num" [class]="tone(surprise(e))">{{ fmtPct(surprise(e), 1) }}</td>
                  </tr>
                } @empty {
                  <tr><td colspan="4" class="muted">No earnings recorded.</td></tr>
                }
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </main>
  `,
})
export class InstrumentPage implements OnInit, OnDestroy {
  private readonly market = inject(MarketService);

  @Input({ required: true }) symbol!: string;

  // Signal query + effect: the chart host sits inside the template and the bars
  // arrive asynchronously, so render when both are ready rather than guessing.
  private readonly chartHost = viewChild<ElementRef<HTMLDivElement>>('priceChart');

  readonly ranges = RANGES;
  readonly instrument = signal<Instrument | null>(null);
  readonly bars = signal<Bar[]>([]);
  readonly news = signal<NewsItem[]>([]);
  readonly earnings = signal<CorporateEvent[]>([]);
  readonly stats = signal<InstrumentStats | null>(null);
  readonly range = signal(252);
  readonly error = signal<string | null>(null);

  private chart?: IChartApi;
  private candles?: ISeriesApi<'Candlestick'>;
  private volume?: ISeriesApi<'Histogram'>;
  private stopThemeWatch?: () => void;
  private resizeObserver?: ResizeObserver;

  readonly fmtPct = pct;
  readonly fmtMoney = money;
  readonly fmtCompact = compact;
  readonly tone = toneClass;

  constructor() {
    effect(() => {
      const host = this.chartHost()?.nativeElement;
      const all = this.bars();
      const days = this.range();
      if (host && all.length) {
        this.renderChart(host, days > 0 ? all.slice(-days) : all);
      }
    });
  }

  ngOnInit(): void {
    const symbol = this.symbol.toUpperCase();
    this.market.instrument(symbol).subscribe({
      next: (i) => this.instrument.set(i),
      error: (err) => this.error.set(err?.error?.detail ?? `Could not load ${symbol}.`),
    });
    this.market.bars(symbol).subscribe({
      next: (b) => this.bars.set(b),
      error: () => void 0,
    });
    this.market.news(symbol).subscribe({ next: (n) => this.news.set(n), error: () => void 0 });
    this.market.events(symbol).subscribe({
      next: (e) => this.earnings.set(e.filter((x) => x.event_type === 'earnings')),
      error: () => void 0,
    });
    this.loadStats();

    this.stopThemeWatch = onThemeChange(() => {
      this.chart?.applyOptions(chartOptions());
      this.applySeriesColors();
    });
  }

  ngOnDestroy(): void {
    this.stopThemeWatch?.();
    this.resizeObserver?.disconnect();
    this.chart?.remove();
  }

  setRange(days: number): void {
    this.range.set(days);   // the effect redraws
    this.loadStats();
  }

  sentimentClass(value: number): string {
    if (value > 0.1) return 'pos';
    if (value < -0.1) return 'neg';
    return '';
  }

  surprise(e: CorporateEvent): number | null {
    if (!e.eps_estimate || !e.eps_actual) return null;
    const est = parseFloat(e.eps_estimate);
    const act = parseFloat(e.eps_actual);
    return est ? ((act - est) / Math.abs(est)) * 100 : null;
  }

  download(kind: string, filename: string): void {
    this.market.download(`${this.symbol.toUpperCase()}/${kind}`, filename).subscribe({
      next: (blob) => {
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
      },
      error: () => this.error.set(`Could not generate ${filename}.`),
    });
  }

  private loadStats(): void {
    const lookback = this.range() || 5000;
    this.market.stats(this.symbol.toUpperCase(), lookback).subscribe({
      next: (s) => this.stats.set(s),
      error: () => void 0,
    });
  }

  private applySeriesColors(): void {
    const up = token('--gain', '#0E7A54');
    const down = token('--loss', '#B33A33');
    this.candles?.applyOptions({
      upColor: up,
      downColor: down,
      borderUpColor: up,
      borderDownColor: down,
      wickUpColor: up,
      wickDownColor: down,
    });
    this.volume?.applyOptions({ color: token('--line', '#DBDFEA') });
  }

  private renderChart(host: HTMLDivElement, data: Bar[]): void {
    if (!this.chart) {
      this.chart = createChart(host, {
        ...chartOptions(),
        width: host.clientWidth,
        height: host.clientHeight || 380,
      });
      this.candles = this.chart.addSeries(CandlestickSeries, { priceLineVisible: false });
      this.volume = this.chart.addSeries(HistogramSeries, {
        priceFormat: { type: 'volume' },
        priceScaleId: 'volume',
        priceLineVisible: false,
        lastValueVisible: false,
      });
      // Park volume in the bottom fifth so it never fights the candles.
      this.chart.priceScale('volume').applyOptions({
        scaleMargins: { top: 0.82, bottom: 0 },
        visible: false,
      });
      this.applySeriesColors();

      this.resizeObserver = new ResizeObserver(() => {
        if (host.clientWidth > 0) {
          this.chart?.applyOptions({ width: host.clientWidth, height: host.clientHeight });
        }
      });
      this.resizeObserver.observe(host);
    }

    this.candles?.setData(
      data.map((b) => ({
        time: toChartDate(b.ts),
        open: parseFloat(b.open),
        high: parseFloat(b.high),
        low: parseFloat(b.low),
        close: parseFloat(b.close),
      })),
    );
    this.volume?.setData(
      data.map((b) => ({ time: toChartDate(b.ts), value: b.volume })),
    );
    this.chart.timeScale().fitContent();
  }
}
