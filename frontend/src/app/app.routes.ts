import { Routes } from '@angular/router';

import { authGuard } from './core/auth.guard';

export const routes: Routes = [
  {
    path: 'login',
    title: 'Sign in',
    loadComponent: () => import('./pages/login/login').then((m) => m.LoginPage),
  },
  {
    path: 'signup',
    title: 'Create account',
    loadComponent: () => import('./pages/signup/signup').then((m) => m.SignupPage),
  },
  {
    path: '',
    canActivate: [authGuard],
    loadComponent: () => import('./shared/shell').then((m) => m.Shell),
    children: [
      { path: '', pathMatch: 'full', redirectTo: 'market' },
      {
        path: 'market',
        title: 'Market',
        loadComponent: () => import('./pages/market/market').then((m) => m.MarketPage),
      },
      {
        path: 'instrument/:symbol',
        title: 'Instrument',
        loadComponent: () =>
          import('./pages/instrument/instrument').then((m) => m.InstrumentPage),
      },
      {
        path: 'dashboard',
        title: 'Account',
        loadComponent: () => import('./pages/dashboard/dashboard').then((m) => m.DashboardPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
