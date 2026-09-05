/** Reads the app's CSS custom properties so charts follow the active theme. */

import { ColorType } from 'lightweight-charts';
import type { ChartOptions, DeepPartial } from 'lightweight-charts';

export function token(name: string, fallback = '#000'): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

export function chartOptions(): DeepPartial<ChartOptions> {
  const ink = token('--ink-3', '#6B7488');
  const line = token('--line', '#DBDFEA');
  return {
    layout: {
      background: { type: ColorType.Solid, color: 'transparent' },
      textColor: ink,
      fontFamily: getComputedStyle(document.body).fontFamily,
      fontSize: 11,
      attributionLogo: false,
    },
    grid: {
      vertLines: { color: line },
      horzLines: { color: line },
    },
    rightPriceScale: { borderColor: line },
    timeScale: { borderColor: line, rightOffset: 4 },
    crosshair: {
      vertLine: { color: ink, width: 1, style: 3, labelBackgroundColor: token('--accent') },
      horzLine: { color: ink, width: 1, style: 3, labelBackgroundColor: token('--accent') },
    },
    handleScale: { axisPressedMouseMove: { price: false } },
  };
}

/** Fires whenever the effective colour scheme changes, so charts can restyle. */
export function onThemeChange(handler: () => void): () => void {
  const mq = window.matchMedia('(prefers-color-scheme: dark)');
  mq.addEventListener('change', handler);
  const observer = new MutationObserver(handler);
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  return () => {
    mq.removeEventListener('change', handler);
    observer.disconnect();
  };
}
