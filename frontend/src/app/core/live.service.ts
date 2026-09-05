import { DestroyRef, Injectable, computed, inject, signal } from '@angular/core';

export interface LiveQuote {
  symbol: string;
  last: number;
  open: number;
  high: number;
  low: number;
  change_pct: number;
  volume: number;
  ts: string;
}

export interface MarketClock {
  session_date: string;
  progress: number;
  open: boolean;
}

const STREAM = '/api/v1/market/stream';
const RECONNECT_MS = 4000;

/**
 * Live quotes over server-sent events.
 *
 * The stream is unauthenticated by design and carries market prices only:
 * EventSource cannot send an Authorization header, and putting a bearer token
 * in the query string would write a credential into browser history and proxy
 * logs. Account data still comes over the authenticated API; positions are
 * revalued here in the browser from these prices.
 */
@Injectable({ providedIn: 'root' })
export class LiveService {
  private readonly destroyRef = inject(DestroyRef);

  private source?: EventSource;
  private reconnectTimer?: ReturnType<typeof setTimeout>;

  readonly quotes = signal<Record<string, LiveQuote>>({});
  readonly clock = signal<MarketClock | null>(null);
  readonly connected = signal(false);

  /** Symbols whose price changed on the most recent frame, for flash highlighting. */
  readonly changed = signal<Set<string>>(new Set());

  readonly sessionProgressPct = computed(() =>
    Math.round((this.clock()?.progress ?? 0) * 100),
  );

  constructor() {
    this.connect();
    this.destroyRef.onDestroy(() => this.disconnect());
  }

  price(symbol: string | null | undefined): number | null {
    if (!symbol) return null;
    return this.quotes()[symbol]?.last ?? null;
  }

  private connect(): void {
    this.disconnect();
    try {
      this.source = new EventSource(STREAM);
    } catch {
      this.scheduleReconnect();
      return;
    }

    this.source.onopen = () => this.connected.set(true);

    this.source.onmessage = (event) => {
      try {
        const payload = JSON.parse(event.data);
        if (payload.type !== 'quotes') return;

        const next: Record<string, LiveQuote> = { ...this.quotes() };
        const moved = new Set<string>();
        for (const q of payload.quotes as LiveQuote[]) {
          if (next[q.symbol]?.last !== q.last) moved.add(q.symbol);
          next[q.symbol] = q;
        }
        this.quotes.set(next);
        this.changed.set(moved);
        this.clock.set({
          session_date: payload.session_date,
          progress: payload.progress,
          open: payload.progress < 1,
        });
      } catch {
        // A malformed frame is not worth tearing the stream down for.
      }
    };

    this.source.onerror = () => {
      this.connected.set(false);
      this.scheduleReconnect();
    };
  }

  private scheduleReconnect(): void {
    if (this.reconnectTimer) return;
    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = undefined;
      this.connect();
    }, RECONNECT_MS);
  }

  private disconnect(): void {
    this.source?.close();
    this.source = undefined;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = undefined;
    }
  }
}
