import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  AgentRunRow,
  Policy,
  PolicyUpdate,
  WatchlistRow,
  DecisionRow,
  NotificationRow,
  OrderRow,
  PositionRow,
  Reconciliation,
  TelegramStatus,
  TradingAccount,
} from './models';

const API = '/api/v1';

@Injectable({ providedIn: 'root' })
export class TradingService {
  private readonly http = inject(HttpClient);

  account(): Observable<TradingAccount> {
    return this.http.get<TradingAccount>(`${API}/trading/account`);
  }

  positions(): Observable<PositionRow[]> {
    return this.http.get<PositionRow[]>(`${API}/trading/positions`);
  }

  orders(limit = 60): Observable<OrderRow[]> {
    return this.http.get<OrderRow[]>(`${API}/trading/orders`, { params: { limit } });
  }

  reconcile(): Observable<Reconciliation> {
    return this.http.get<Reconciliation>(`${API}/trading/reconcile`);
  }

  // --- agent ---

  runs(limit = 20): Observable<AgentRunRow[]> {
    return this.http.get<AgentRunRow[]>(`${API}/agent/runs`, { params: { limit } });
  }

  runDecisions(runId: string): Observable<DecisionRow[]> {
    return this.http.get<DecisionRow[]>(`${API}/agent/runs/${runId}/decisions`);
  }

  decisions(limit = 60): Observable<DecisionRow[]> {
    return this.http.get<DecisionRow[]>(`${API}/agent/decisions`, { params: { limit } });
  }

  tick(dryRun = false): Observable<Record<string, unknown>> {
    return this.http.post<Record<string, unknown>>(
      `${API}/agent/tick`,
      {},
      { params: { dry_run: dryRun } },
    );
  }

  haltStatus(): Observable<{ halted: boolean }> {
    return this.http.get<{ halted: boolean }>(`${API}/agent/halt`);
  }

  setHalt(reason = 'from the dashboard'): Observable<unknown> {
    return this.http.post(`${API}/agent/halt`, {}, { params: { reason } });
  }

  clearHalt(): Observable<unknown> {
    return this.http.delete(`${API}/agent/halt`);
  }

  // --- policy and watchlist ---

  policy(): Observable<Policy> {
    return this.http.get<Policy>(`${API}/trading/policy`);
  }

  updatePolicy(changes: PolicyUpdate): Observable<Policy> {
    return this.http.patch<Policy>(`${API}/trading/policy`, changes);
  }

  watchlist(): Observable<WatchlistRow[]> {
    return this.http.get<WatchlistRow[]>(`${API}/trading/watchlist`);
  }

  addToWatchlist(symbol: string, conviction = 2): Observable<WatchlistRow> {
    return this.http.post<WatchlistRow>(
      `${API}/trading/watchlist/${symbol}`,
      {},
      { params: { conviction } },
    );
  }

  removeFromWatchlist(symbol: string): Observable<void> {
    return this.http.delete<void>(`${API}/trading/watchlist/${symbol}`);
  }

  // --- notifications ---

  notifications(limit = 40): Observable<NotificationRow[]> {
    return this.http.get<NotificationRow[]>(`${API}/notifications`, { params: { limit } });
  }

  telegram(): Observable<TelegramStatus> {
    return this.http.get<TelegramStatus>(`${API}/notifications/telegram`);
  }

  linkTelegram(): Observable<{ code: string; instructions: string; configured: boolean }> {
    return this.http.post<{ code: string; instructions: string; configured: boolean }>(
      `${API}/notifications/telegram/link`,
      {},
    );
  }
}
