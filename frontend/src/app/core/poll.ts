import { DestroyRef } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { Subscription, timer } from 'rxjs';

/**
 * Re-run `fetch` on a timer for as long as the component lives.
 *
 * Account state - cash, holdings, the order list - cannot ride the quote
 * stream: that stream is deliberately unauthenticated and carries public
 * market prices only, so putting one user's balance on it would broadcast it
 * to every listener. Polling an authenticated endpoint is the honest way to
 * keep those numbers current.
 *
 * After the initial load, nothing is fetched while the tab is hidden - a
 * background tab that keeps asking is load nobody is looking at - and a fetch
 * fires immediately when it becomes visible again, so returning to the tab
 * shows fresh numbers rather than whatever was on screen when it was left.
 */
export function pollWhileAlive(
  destroyRef: DestroyRef,
  fetch: () => void,
  everyMs = 5000,
): void {
  // The first fetch is unconditional. A tab can be hidden the moment it is
  // created - restored on startup, opened in the background, prerendered - and
  // gating the initial load on visibility leaves those pages stuck on their
  // loading state until someone happens to look at them.
  fetch();

  const onVisible = () => {
    if (!document.hidden) fetch();
  };
  document.addEventListener('visibilitychange', onVisible);

  const subscription: Subscription = timer(everyMs, everyMs)
    .pipe(takeUntilDestroyed(destroyRef))
    .subscribe(() => {
      if (!document.hidden) fetch();
    });

  destroyRef.onDestroy(() => {
    document.removeEventListener('visibilitychange', onVisible);
    subscription.unsubscribe();
  });
}
