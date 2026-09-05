import { HttpClient } from '@angular/common/http';
import { Injectable, inject } from '@angular/core';
import { Observable } from 'rxjs';

import {
  Bar,
  CorporateEvent,
  IndexPoint,
  Instrument,
  InstrumentStats,
  MarketOverview,
  NewsItem,
  SectorPerf,
} from './models';

const API = '/api/v1';

@Injectable({ providedIn: 'root' })
export class MarketService {
  private readonly http = inject(HttpClient);

  overview(): Observable<MarketOverview> {
    return this.http.get<MarketOverview>(`${API}/analytics/overview`);
  }

  indexHistory(limit = 1500): Observable<IndexPoint[]> {
    return this.http.get<IndexPoint[]>(`${API}/analytics/index`, {
      params: { limit },
    });
  }

  sectors(window = '1d'): Observable<SectorPerf[]> {
    return this.http.get<SectorPerf[]>(`${API}/analytics/sectors`, {
      params: { window },
    });
  }

  instruments(search?: string, sector?: string): Observable<Instrument[]> {
    const params: Record<string, string | number> = { limit: 500 };
    if (search) params['search'] = search;
    if (sector) params['sector'] = sector;
    return this.http.get<Instrument[]>(`${API}/market/instruments`, { params });
  }

  instrument(symbol: string): Observable<Instrument> {
    return this.http.get<Instrument>(`${API}/market/instruments/${symbol}`);
  }

  bars(symbol: string, limit = 1500): Observable<Bar[]> {
    return this.http.get<Bar[]>(`${API}/market/instruments/${symbol}/bars`, {
      params: { limit },
    });
  }

  news(symbol: string, limit = 20): Observable<NewsItem[]> {
    return this.http.get<NewsItem[]>(`${API}/market/instruments/${symbol}/news`, {
      params: { limit },
    });
  }

  events(symbol: string, limit = 12): Observable<CorporateEvent[]> {
    return this.http.get<CorporateEvent[]>(`${API}/market/instruments/${symbol}/events`, {
      params: { limit },
    });
  }

  stats(symbol: string, lookback = 252): Observable<InstrumentStats> {
    return this.http.get<InstrumentStats>(`${API}/analytics/stats/${symbol}`, {
      params: { lookback },
    });
  }

  digest(): Observable<{ as_of: string; text: string }> {
    return this.http.get<{ as_of: string; text: string }>(`${API}/analytics/digest`);
  }

  /** Exports need the auth header, so fetch as a blob and hand the browser a link. */
  download(path: string, filename: string): Observable<Blob> {
    return this.http.get(`${API}/analytics/export/${path}`, { responseType: 'blob' });
  }
}
