/** Human labels for the pattern/category codes the backend returns.
 *
 * Mirrors `PATTERN_LABELS` / `PCFG_CATEGORY_LABELS` in
 * `scripts/check_password.py` — the terminal-facing CLI and this UI should
 * describe the same codes the same way. Presentation only: it renames
 * nothing the backend sends, it just supplies a friendlier string next to
 * the code the backend actually used.
 */

export const PATTERN_LABELS: Record<string, string> = {
  indic_word: "Indic dictionary match",
  digits: "Numeric run",
  year: "Year",
  symbols: "Symbol run",
  repeat: "Repeated characters",
  bruteforce: "Unrecognised span",
};

export const PCFG_CATEGORY_LABELS: Record<string, string> = {
  word: "Indic dictionary word",
  unknown: "Unseen spelling (priced by the character model)",
  digits: "Numeric run",
  year: "Year",
  symbols: "Symbol run",
};

export const STRENGTH_COLORS: readonly string[] = [
  "#dc2626", // 0 Very Weak
  "#ea580c", // 1 Weak
  "#ca8a04", // 2 Fair
  "#16a34a", // 3 Strong
  "#0d9488", // 4 Very Strong
];

export function strengthColor(score: number): string {
  return STRENGTH_COLORS[Math.min(Math.max(score, 0), STRENGTH_COLORS.length - 1)];
}

export function patternLabel(pattern: string): string {
  return PATTERN_LABELS[pattern] ?? pattern;
}

export function pcfgCategoryLabel(category: string): string {
  return PCFG_CATEGORY_LABELS[category] ?? category;
}
