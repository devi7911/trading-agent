import {
  Component,
  ElementRef,
  OnDestroy,
  OnInit,
  computed,
  effect,
  inject,
  signal,
  viewChild,
} from '@angular/core';
import { RouterLink } from '@angular/router';
import { AreaSeries, createChart } from 'lightweight-charts';
import type { IChartApi, ISeriesApi } from 'lightweight-charts';

import { MarketService } from '../../core/market.service';
import { IndexPoint, MarketOverview, SectorPerf } from '../../core/models';
import { chartOptions, onThemeChange, token } from '../../shared/chart-theme';
import { compact, money, pct, toChartDate, toneClass } from '../../shared/format';

const WINDOWS = [
  { key: '1d', label: '1D' },
  { key: '1w', label: '1W' },
  { key: '1m', label: '1M' },
  { key: '3m', label: '3M' },
  { key: 'ytd', label: 'YTD' },
  { key: '1y', label: '1Y' },
];

@Component({
  selector: 'app-market',
  imports: [RouterLink],
  template: `
    <main class="page">
      @if (error()) {
        <div class="alert" role="alert">{{ error() }}</div>
      }

      @if (overview(); as o) {
        <div class="page__head">
          <div>
            <h1 style="margin-bottom:6px">Market</h1>
            <p class="muted" style="margin:0">
              Simulated universe · {{ o.as_of.slice(0, 10) }}
              @if (o.index.regime) {
                <span class="regime" [class]="'regime ' + o.index.regime" style="margin-left:8px">
                  {{ o.index.regime }}
                </span>
              }
            </p>
          </div>
          <div class="toolbar">
            <button class="chip" type="button" (click)="download('market.xlsx', 'market.xlsx')">
              Excel
            </button>
            <button class="chip" type="button" (click)="download('universe.csv', 'universe.csv')">
              CSV
            </button>
          </div>
        </div>

        <!-- headline tiles -->
        <div class="grid grid--tiles" style="margin-bottom:14px">
          <div class="tile">
            <div class="tile__label">Index</div>
            <div class="tile__value">{{ fmtMoney(o.index.value, 1) }}</div>
            <div class="tile__sub" [class]="tone(o.index.change_pct)">
              {{ fmtPct(o.index.change_pct) }} today
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Breadth</div>
            <div class="tile__value">{{ o.breadth.advancers }} / {{ o.breadth.decliners }}</div>
            <div class="breadth" [attr.aria-label]="breadthLabel(o)">
              <div class="breadth__up" [style.width.%]="share(o, 'advancers')"></div>
              <div class="breadth__flat" [style.width.%]="share(o, 'unchanged')"></div>
              <div class="breadth__down" [style.width.%]="share(o, 'decliners')"></div>
            </div>
          </div>
          <div class="tile">
            <div class="tile__label">Above 50-day</div>
            <div class="tile__value">{{ o.breadth.pct_above_50dma.toFixed(0) }}%</div>
            <div class="tile__sub">of the universe</div>
          </div>
          <div class="tile">
            <div class="tile__label">New highs / lows</div>
            <div class="tile__value">{{ o.breadth.new_highs }} / {{ o.breadth.new_lows }}</div>
            <div class="tile__sub">52-week</div>
          </div>
          <div class="tile">
            <div class="tile__label">Volume</div>
            <div class="tile__value">{{ fmtCompact(o.total_volume) }}</div>
            <div class="tile__sub">shares traded</div>
          </div>
        </div>

        <!-- index chart -->
        <section class="panel" style="margin-bottom:14px">
          <div class="panel__head">
            <h2 class="panel__title">Index history</h2>
            <span class="muted mono">{{ points().length }} sessions</span>
          </div>
          <div class="panel__body panel__body--flush">
            <div #indexChart class="chart"></div>
          </div>
        </section>

        <div class="grid grid--split" style="margin-bottom:14px">
          <!-- sectors -->
          <section class="panel">
            <div class="panel__head">
              <h2 class="panel__title">Sector performance</h2>
              <div class="toolbar">
                @for (w of windows; track w.key) {
                  <button
                    class="chip"
                    type="button"
                    [class.active]="sectorWindow() === w.key"
                    (click)="setSectorWindow(w.key)"
                  >
                    {{ w.label }}
                  </button>
                }
              </div>
            </div>
            <div class="panel__body">
              @for (s of sectors(); track s.sector) {
                <div class="sector-row">
                  <span class="sector-row__name">{{ s.sector }}</span>
                  <span class="sector-row__track">
                    <span
                      class="sector-row__fill"
                      [style.left.%]="s.return_pct >= 0 ? 50 : 50 - barWidth(s)"
                      [style.width.%]="barWidth(s)"
                      [style.background]="s.return_pct >= 0 ? gainColor : lossColor"
                    ></span>
                  </span>
                  <span class="sector-row__value" [class]="tone(s.return_pct)">
                    {{ fmtPct(s.return_pct, 1) }}
                  </span>
                </div>
              } @empty {
                <p class="muted">No sector data.</p>
              }
            </div>
          </section>

          <!-- most active -->
          <section class="panel">
            <div class="panel__head"><h2 class="panel__title">Most active</h2></div>
            <div class="panel__body panel__body--flush tablewrap">
              <table class="data">
                <thead>
                  <tr>
                    <th>Symbol</th>
                    <th>Sector</th>
                    <th class="num">Last</th>
                    <th class="num">Change</th>
                    <th class="num">Rel vol</th>
                  </tr>
                </thead>
                <tbody>
                  @for (m of o.most_active; track m.symbol) {
                    <tr>
                      <td class="sym"><a [routerLink]="['/instrument', m.symbol]">{{ m.symbol }}</a></td>
                      <td class="muted">{{ m.sector }}</td>
                      <td class="num">{{ fmtMoney(m.close) }}</td>
                      <td class="num" [class]="tone(m.change_pct)">{{ fmtPct(m.change_pct) }}</td>
                      <td class="num">{{ m.relative_volume.toFixed(1) }}×</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <!-- movers -->
        <div class="grid grid--split">
          <section class="panel">
            <div class="panel__head"><h2 class="panel__title">Gainers</h2></div>
            <div class="panel__body panel__body--flush tablewrap">
              <table class="data">
                <thead>
                  <tr><th>Symbol</th><th>Sector</th><th class="num">Last</th><th class="num">Change</th></tr>
                </thead>
                <tbody>
                  @for (m of o.gainers; track m.symbol) {
                    <tr>
                      <td class="sym"><a [routerLink]="['/instrument', m.symbol]">{{ m.symbol }}</a></td>
                      <td class="muted">{{ m.sector }}</td>
                      <td class="num">{{ fmtMoney(m.close) }}</td>
                      <td class="num gain">{{ fmtPct(m.change_pct) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </section>

          <section class="panel">
            <div class="panel__head"><h2 class="panel__title">Losers</h2></div>
            <div class="panel__body panel__body--flush tablewrap">
              <table class="data">
                <thead>
                  <tr><th>Symbol</th><th>Sector</th><th class="num">Last</th><th class="num">Change</th></tr>
                </thead>
                <tbody>
                  @for (m of o.losers; track m.symbol) {
                    <tr>
                      <td class="sym"><a [routerLink]="['/instrument', m.symbol]">{{ m.symbol }}</a></td>
                      <td class="muted">{{ m.sector }}</td>
                      <td class="num">{{ fmtMoney(m.close) }}</td>
                      <td class="num loss">{{ fmtPct(m.change_pct) }}</td>
                    </tr>
                  }
                </tbody>
              </table>
            </div>
          </section>
        </div>
      } @else if (!error()) {
        <p class="spinner">Loading market…</p>
      }
    </main>
  `,
})
export class MarketPage implements OnInit, OnDestroy {
  private readonly market = inject(MarketService);

  // The chart element lives inside an @if, so it does not exist when the data
  // callback fires. A signal query plus an effect renders as soon as BOTH the
  // element and the data are available, whichever arrives second.
  private readonly chartHost = viewChild<ElementRef<HTMLDivElement>>('indexChart');

  readonly windows = WINDOWS;
  readonly overview = signal<MarketOverview | null>(null);
  readonly points = signal<IndexPoint[]>([]);
  readonly sectors = signal<SectorPerf[]>([]);
  readonly sectorWindow = signal('1d');
  readonly error = signal<string | null>(null);

  readonly maxSectorMove = computed(() =>
    Math.max(0.5, ...this.sectors().map((s) => Math.abs(s.return_pct))),
  );

  gainColor = '#0E7A54';
  lossColor = '#B33A33';

  private chart?: IChartApi;
  private series?: ISeriesApi<'Area'>;
  private stopThemeWatch?: () => void;
  private resizeObserver?: ResizeObserver;

  readonly fmtPct = pct;
  readonly fmtMoney = money;
  readonly fmtCompact = compact;
  readonly tone = toneClass;

  constructor() {
    effect(() => {
      const host = this.chartHost()?.nativeElement;
      const data = this.points();
      if (host && data.length) {
        this.renderChart(host, data);
      }
    });
  }

  ngOnInit(): void {
    this.market.overview().subscribe({
      next: (o) => {
        this.overview.set(o);
        this.sectors.set(o.sectors);
      },
      error: (err) =>
        this.error.set(
          err?.error?.detail ?? 'Could not load the market. Is the API running?',
        ),
    });

    this.market.indexHistory().subscribe({
      next: (p) => this.points.set(p),
      error: () => void 0,
    });

    this.gainColor = token('--gain', '#0E7A54');
    this.lossColor = token('--loss', '#B33A33');
    this.stopThemeWatch = onThemeChange(() => {
      this.gainColor = token('--gain', '#0E7A54');
      this.lossColor = token('--loss', '#B33A33');
      this.chart?.applyOptions(chartOptions());
      this.applySeriesColors();
    });
  }

  ngOnDestroy(): void {
    this.stopThemeWatch?.();
    this.resizeObserver?.disconnect();
    this.chart?.remove();
  }

  setSectorWindow(window: string): void {
    this.sectorWindow.set(window);
    this.market.sectors(window).subscribe({
      next: (s) => this.sectors.set(s),
      error: () => void 0,
    });
  }

  barWidth(s: SectorPerf): number {
    return Math.min(50, (Math.abs(s.return_pct) / this.maxSectorMove()) * 48);
  }

  share(o: MarketOverview, key: 'advancers' | 'decliners' | 'unchanged'): number {
    const total = o.breadth.advancers + o.breadth.decliners + o.breadth.unchanged;
    return total ? (o.breadth[key] / total) * 100 : 0;
  }

  breadthLabel(o: MarketOverview): string {
    return `${o.breadth.advancers} advancing, ${o.breadth.decliners} declining, ${o.breadth.unchanged} unchanged`;
  }

  download(path: string, filename: string): void {
    this.market.download(path, filename).subscribe({
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

  private applySeriesColors(): void {
    this.series?.applyOptions({
      lineColor: token('--accent', '#2F4FC4'),
      topColor: token('--accent', '#2F4FC4') + '38',
      bottomColor: token('--accent', '#2F4FC4') + '05',
    });
  }

  private renderChart(host: HTMLDivElement, data: IndexPoint[]): void {
    if (!this.chart) {
      this.chart = createChart(host, {
        ...chartOptions(),
        width: host.clientWidth,
        height: host.clientHeight || 380,
      });
      this.series = this.chart.addSeries(AreaSeries, {
        lineWidth: 2,
        priceLineVisible: false,
        lastValueVisible: true,
      });
      this.applySeriesColors();

      this.resizeObserver = new ResizeObserver(() => {
        if (host.clientWidth > 0) {
          this.chart?.applyOptions({ width: host.clientWidth, height: host.clientHeight });
        }
      });
      this.resizeObserver.observe(host);
    }

    this.series?.setData(
      data.map((p) => ({ time: toChartDate(p.ts), value: p.index_value })),
    );
    this.chart.timeScale().fitContent();
  }
}
