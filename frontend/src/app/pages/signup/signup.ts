import { Component, inject, signal } from '@angular/core';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';

import { AuthService } from '../../core/auth.service';

@Component({
  selector: 'app-signup',
  imports: [ReactiveFormsModule, RouterLink],
  template: `
    <main class="centered">
      <form class="card stack-form" [formGroup]="form" (ngSubmit)="submit()" novalidate>
        <h1>Create your account</h1>
        <p class="muted">
          You get a simulated account funded with $100,000. No real money is ever involved.
        </p>

        @if (error()) {
          <div class="alert" role="alert">{{ error() }}</div>
        }

        <div class="field">
          <label for="name">Name <span class="hint">(optional)</span></label>
          <input id="name" type="text" autocomplete="name" formControlName="displayName" />
        </div>

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
            autocomplete="new-password"
            formControlName="password"
            aria-describedby="pw-hint"
            [attr.aria-invalid]="isInvalid('password')"
          />
          <span class="hint" id="pw-hint">At least 10 characters.</span>
          @if (isInvalid('password')) {
            <span class="error">Password must be at least 10 characters.</span>
          }
        </div>

        <button type="submit" [disabled]="busy()">
          {{ busy() ? 'Creating…' : 'Create account' }}
        </button>

        <p class="muted" style="margin-top:18px">
          Already have one? <a routerLink="/login">Sign in</a>
        </p>
      </form>
    </main>
  `,
})
export class SignupPage {
  private readonly fb = inject(FormBuilder);
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);

  readonly busy = signal(false);
  readonly error = signal<string | null>(null);

  readonly form = this.fb.nonNullable.group({
    displayName: [''],
    email: ['', [Validators.required, Validators.email]],
    password: ['', [Validators.required, Validators.minLength(10)]],
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
    const { email, password, displayName } = this.form.getRawValue();

    this.auth.signup(email, password, displayName).subscribe({
      next: () => void this.router.navigate(['/dashboard']),
      error: (err) => {
        this.busy.set(false);
        this.error.set(err?.error?.detail ?? 'Could not create the account. Try again.');
      },
    });
  }
}
