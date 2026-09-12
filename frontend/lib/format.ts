/** Formatting helpers for the guess-number scale, which runs from 1 to
 * numbers with dozens of digits — a plain `toLocaleString` is unreadable
 * past a few thousand, and the raw float can be `Infinity` (see
 * `parseIndicPassJson` in `lib/api.ts`).
 */

export function formatGuesses(value: number): string {
  if (Number.isNaN(value)) return "unknown";
  if (!Number.isFinite(value)) return "effectively unlimited";
  if (value < 1) return value.toString();
  if (value < 100000) {
    return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  }
  const exponent = Math.floor(Math.log10(value));
  const mantissa = value / 10 ** exponent;
  return `${mantissa.toFixed(2)} × 10^${exponent}`;
}

export function formatLog10(value: number | undefined): string {
  if (value === undefined || Number.isNaN(value)) return "—";
  if (!Number.isFinite(value)) return "∞";
  return value.toFixed(2);
}

export function formatPercent(value: number, digits = 1): string {
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatCount(value: number): string {
  return value.toLocaleString();
}
