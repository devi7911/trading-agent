import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../core/auth.service';
import { LiveService } from '../core/live.service';

@Component({
  selector: 'app-shell',
  imports: [RouterOutlet, RouterLink, RouterLinkActive],
  template: `
    <header class="appbar">
      <div class="appbar__inner">
        <div class="appbar__brand">Trading<span>Desk</span></div>
        <nav aria-label="Main">
          <a routerLink="/portfolio" routerLinkActive="active">Portfolio</a>
          <a routerLink="/agent" routerLinkActive="active">Agent</a>
          <a routerLink="/market" routerLinkActive="active">Market</a>
          <a routerLink="/settings" routerLinkActive="active">Settings</a>
        </nav>

        <div class="live" [attr.aria-live]="'polite'">
          <span class="live__dot" [class.on]="live.connected()"></span>
          @if (live.clock(); as c) {
            <span class="live__text">
              {{ c.session_date }} · {{ live.sessionProgressPct() }}% through the session
            </span>
          } @else {
            <span class="live__text muted">market closed</span>
          }
        </div>

        <button class="ghost" type="button" (click)="auth.logout()">Sign out</button>
      </div>
    </header>
    <router-outlet />
  `,
  styles: [
    `
      .live {
        display: flex;
        align-items: center;
        gap: 8px;
        font-family: var(--font-mono);
        font-size: 0.72rem;
        color: var(--ink-3);
        white-space: nowrap;
      }
      .live__dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: var(--ink-3);
        flex-shrink: 0;
      }
      .live__dot.on {
        background: var(--gain);
        animation: pulse 2s ease-in-out infinite;
      }
      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.35; }
      }
      @media (prefers-reduced-motion: reduce) {
        .live__dot.on { animation: none; }
      }
      @media (max-width: 900px) {
        .live__text { display: none; }
      }
    `,
  ],
})
export class Shell {
  readonly auth = inject(AuthService);
  readonly live = inject(LiveService);
}
