import { Component, OnInit, inject, signal } from '@angular/core';

import { AuthService } from '../../core/auth.service';
import { HealthService } from '../../core/health.service';
import { HealthStatus } from '../../core/models';

@Component({
  selector: 'app-dashboard',
  template: `
    <main class="page">
      <div class="page__head">
        <div>
          <h1 style="margin-bottom:4px">
            {{ auth.currentUser()?.display_name || 'Account' }}
          </h1>
          <p class="muted" style="margin:0">{{ auth.currentUser()?.email }}</p>
        </div>
      </div>

      <section class="panel" style="margin-bottom:14px"><div class="panel__body">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:16px">
          <h2 style="margin:0">System status</h2>
          @if (health(); as h) {
            <span class="pill" [class]="'pill ' + h.status">{{ h.status }}</span>
          }
        </div>

        @if (health(); as h) {
          <dl
            style="display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:16px;margin:20px 0 0"
          >
            @for (check of checks(h); track check.name) {
              <div>
                <dt class="muted" style="text-transform:uppercase;font-size:.72rem;letter-spacing:.1em">
                  {{ check.name }}
                </dt>
                <dd class="mono" style="margin:2px 0 0">{{ check.value }}</dd>
              </div>
            }
            <div>
              <dt class="muted" style="text-transform:uppercase;font-size:.72rem;letter-spacing:.1em">
                API version
              </dt>
              <dd class="mono" style="margin:2px 0 0">{{ h.version }}</dd>
            </div>
          </dl>
        } @else if (healthError()) {
          <p class="muted" style="margin:16px 0 0">{{ healthError() }}</p>
        } @else {
          <p class="muted" style="margin:16px 0 0">Checking…</p>
        }
      </div></section>

      <section class="panel"><div class="panel__body">
        <h2>Where this is</h2>
        <p class="muted">
          Auth, database, market data and analytics are wired up. There is no agent yet
          and nothing is trading.
        </p>
        <p class="muted" style="margin:0">
          A full synthetic market is loaded and browsable. Next is the simulated
          exchange: matching engine, order lifecycle, and positions derived from fills.
        </p>
      </div></section>
    </main>
  `,
})
export class DashboardPage implements OnInit {
  readonly auth = inject(AuthService);
  private readonly healthService = inject(HealthService);

  readonly health = signal<HealthStatus | null>(null);
  readonly healthError = signal<string | null>(null);

  ngOnInit(): void {
    this.auth.loadMe().subscribe({ error: () => void 0 });
    this.healthService.readiness().subscribe({
      next: (h) => this.health.set(h),
      error: () => this.healthError.set('Could not reach the API.'),
    });
  }

  checks(h: HealthStatus): { name: string; value: string }[] {
    return Object.entries(h.checks).map(([name, value]) => ({ name, value }));
  }
}
