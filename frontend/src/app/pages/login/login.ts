import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-login',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <main class="centered">
      <form class="card stack-form" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <h1>Sign in</h1>
        <p class="muted">Your agent keeps running whether this page is open or not.</p>

        @if (error()) {
          <div class="alert" role="alert">{{ error() }}</div>
        }

        <div class="field">
          <label for="email">Email</label>
          <input
            id="email"
            type="email"
            autocomplete="email"
            formControlName="email"
            [attr.aria-invalid]="isInvalid('email')"
          />
          @if (isInvalid('email')) {
            <span class="error">Enter a valid email address.</span>
          }
        </div>

        <div class="field">
          <label for="password">Password</label>
          <input
            id="password"
            type="password"
            autocomplete="current-password"
            formControlName="password"
            [attr.aria-invalid]="isInvalid('password')"
          />
          @if (isInvalid('password')) {
            <span class="error">Password is required.</span>
          }
        </div>

        <button type="submit" [disabled]="busy()">
          {{ busy() ? 'Signing in…' : 'Sign in' }}
        </button>

        <p class="muted" style="margin-top:18px">
          No account yet? <a routerLink="/signup">Create one</a>
        </p>
      </form>
    </main>
  `,
})
export class LoginPage {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required]],
  });

  isInvalid(name: string): boolean {
    const c = this.form.get(name);
    return !!c && c.invalid && (c.dirty || c.touched);
  }

  submit(): void {
    if (this.form.invalid) {
      this.form.markAllAsTouched();
      return;
    }
    this.busy.set(true);
    this.error.set(null);
    const { email, password } = this.form.getRawValue();

    this.auth.login(email, password).subscribe({
      next: () => void this.router.navigate(['/dashboard']),
      error: (err) => {
        this.busy.set(false);
        this.error.set(
          err?.error?.detail ?? 'Could not sign in. Check the API is running and try again.',
        );
      },
    });
  }
}
