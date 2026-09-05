import { Component, OnInit, inject, signal } from '@angular/core';

import { AuthService } from '../../core/auth.service';
import { HealthService } from '../../core/health.service';
import { HealthStatus } from '../../core/models';

@Component({
  selector: 'app-dashboard',
  template: `
    <main style="max-width:900px;margin:0 auto;padding:40px 24px">
      <header
        style="display:flex;justify-content:space-between;align-items:flex-start;gap:20px;margin-bottom:32px"
      >
        <div>
          <h1 style="margin-bottom:4px">
            {{ auth.currentUser()?.display_name || 'Welcome' }}
          </h1>
          <p class="muted" style="margin:0">{{ auth.currentUser()?.email }}</p>
        </div>
        <button class="ghost" type="button" (click)="auth.logout()">Sign out</button>
      </header>

      <section class="card" style="margin-bottom:20px">
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
      </section>

      <section class="card">
        <h2>Phase 00 complete</h2>
        <p class="muted">
          Auth, database, migrations, Redis and health checks are wired up. There is no agent yet
          and nothing is trading — that starts with the market data spine in phase 01.
        </p>
        <p class="muted" style="margin:0">
          Next: synthetic universe generator, seeded price paths, and bars flowing into TimescaleDB.
        </p>
      </section>
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
