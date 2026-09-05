/** Small formatting helpers shared by the market screens. */

export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—';
  return `${value >= 0 ? '+' : ''}${value.toFixed(digits)}%`;
}

export function money(value: number | string | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—';
  const n = typeof value === 'string' ? parseFloat(value) : value;
  return n.toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function compact(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
  if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${(value / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${(value / 1e3).toFixed(1)}K`;
  return value.toFixed(0);
}

export function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined || Math.abs(value) < 0.005) return 'flat';
  return value > 0 ? 'gain' : 'loss';
}

/** lightweight-charts wants YYYY-MM-DD for daily series. */
export function toChartDate(iso: string): string {
  return iso.slice(0, 10);
}
