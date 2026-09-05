import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive, RouterOutlet } from '@angular/router';

import { AuthService } from '../core/auth.service';

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
        <button class="ghost" type="button" (click)="auth.logout()">Sign out</button>
      </div>
    </header>
    <router-outlet />
  `,
})
export class Shell {
  readonly auth = inject(AuthService);
}
