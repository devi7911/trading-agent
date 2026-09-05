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
      { path: '', pathMatch: 'full', redirectTo: 'portfolio' },
      {
        path: 'portfolio',
        title: 'Portfolio',
        loadComponent: () => import('./pages/portfolio/portfolio').then((m) => m.PortfolioPage),
      },
      {
        path: 'agent',
        title: 'Agent',
        loadComponent: () => import('./pages/agent/agent').then((m) => m.AgentPage),
      },
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
        path: 'settings',
        title: 'Settings',
        loadComponent: () => import('./pages/settings/settings').then((m) => m.SettingsPage),
      },
    ],
  },
  { path: '**', redirectTo: '' },
];
