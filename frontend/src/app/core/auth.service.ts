import { HttpClient } from '@angular/common/http';
import { Injectable, computed, inject, signal } from '@angular/core';
import { Router } from '@angular/router';
import { Observable, tap } from 'rxjs';

import { TokenPair, User } from './models';

const ACCESS_KEY = 'ta.access_token';
const REFRESH_KEY = 'ta.refresh_token';

@Injectable({ providedIn: 'root' })
export class AuthService {
  private readonly http = inject(HttpClient);
  private readonly router = inject(Router);

  private readonly accessToken = signal<string | null>(this.read(ACCESS_KEY));
  readonly currentUser = signal<User | null>(null);
  readonly isAuthenticated = computed(() => this.accessToken() !== null);

  token(): string | null {
    return this.accessToken();
  }

  signup(email: string, password: string, displayName?: string): Observable<TokenPair> {
    return this.http
      .post<TokenPair>('/api/v1/auth/signup', {
        email,
        password,
        display_name: displayName || null,
      })
      .pipe(tap((t) => this.store(t)));
  }

  login(email: string, password: string): Observable<TokenPair> {
    return this.http
      .post<TokenPair>('/api/v1/auth/login', { email, password })
      .pipe(tap((t) => this.store(t)));
  }

  loadMe(): Observable<User> {
    return this.http.get<User>('/api/v1/auth/me').pipe(tap((u) => this.currentUser.set(u)));
  }

  logout(): void {
    localStorage.removeItem(ACCESS_KEY);
    localStorage.removeItem(REFRESH_KEY);
    this.accessToken.set(null);
    this.currentUser.set(null);
    void this.router.navigate(['/login']);
  }

  private store(tokens: TokenPair): void {
    localStorage.setItem(ACCESS_KEY, tokens.access_token);
    localStorage.setItem(REFRESH_KEY, tokens.refresh_token);
    this.accessToken.set(tokens.access_token);
  }

  private read(key: string): string | null {
    try {
      return localStorage.getItem(key);
    } catch {
      return null;
    }
  }
}
