/**
 * Types mirroring the JSON the IndicPass API returns.
 *
 * These describe the existing `PasswordStrengthResult.to_dict()` shape from
 * `src/indicpass/password/result.py` (plus the `dictionaries` / `estimators`
 * blocks `scripts/check_password.py --json` already adds) — not a schema
 * invented for this frontend. Fields are optional/loosely typed wherever the
 * backend only includes them conditionally (e.g. `pcfg` when no grammar is
 * attached, `native_form`/`token` only when `reveal_tokens` was requested),
 * and every interface keeps an index signature so an unrecognised field from
 * the backend degrades gracefully instead of getting dropped.
 */

export interface Match {
  pattern: string; // indic_word | digits | year | symbols | repeat | bruteforce
  start: number;
  end: number;
  length: number;
  guesses: number;
  log10_guesses: number;
  /** Only present when the request asked to reveal matched substrings. */
  token?: string;
  /** Devanagari rendering of a dictionary hit — also reveal-gated. */
  native_form?: string;
  language?: string;
  match_class?: string;
  class_penalty?: number;
  rank_policy?: string;
  wordlist_position?: number;
  tier?: string;
  tier_size?: number;
  tier_offset?: number;
  model_verified?: boolean;
  case_transformation?: string;
  case_variations?: number;
  is_named_entity?: boolean;
  frequency?: number;
  rank?: number;
  frequency_source?: string;
  year_range?: [number, number];
  [key: string]: unknown;
}

export interface IndicpassBlock {
  guesses: number;
  log10_guesses: number;
  score: number;
  label: string;
  matches: Match[];
}

export interface BaselineBlock {
  guesses: number;
  log10_guesses: number;
  score: number;
  patterns: string[];
  feedback: string[];
}

export interface PcfgSegment {
  category: string;
  start: number;
  end: number;
  length: number;
  log10_terminal: number;
  log10_category: number;
  log10_probability: number;
  rank?: number;
  tier?: string;
  observed_frequency?: boolean;
  year_range?: [number, number];
  [key: string]: unknown;
}

export interface PcfgBlock {
  guesses: number;
  log10_guesses: number;
  score: number;
  label: string;
  log10_probability: number;
  grammar_log10_guesses: number;
  bruteforce_log10_guesses: number;
  floor_applied: boolean;
  supported: boolean;
  structure: string[];
  log10_structure_prior: number;
  segments: PcfgSegment[];
}

export interface FrequencySource {
  identifier: string;
  provider?: string;
  version?: string;
  language?: string;
  semantics?: string;
  entries?: number;
  [key: string]: unknown;
}

export interface DictionaryTier {
  name: string;
  index: number;
  size: number;
  ranked_size: number;
  unranked_size: number;
  offset: number;
  [key: string]: unknown;
}

export interface DictionaryInfo {
  language: string;
  entries: number;
  tiers: DictionaryTier[];
  frequency_available: boolean;
  ranked_entries: number;
  frequency_coverage: number;
  frequency_source: FrequencySource | null;
  built_at?: string | null;
  git_commit?: string | null;
}

export interface EstimatorAvailability {
  indicpass: boolean;
  baseline: string | null;
  pcfg: boolean;
}

/**
 * The full response body of `POST /api/analyze`.
 *
 * `[baselineName]` (e.g. `zxcvbn`) is a dynamically-named nested block —
 * `PasswordStrengthResult.to_dict` names it after whichever baseline
 * implementation is configured — so it is read through `estimators.baseline`
 * at call sites (see `getBaselineBlock` in `lib/api.ts`) rather than assumed
 * to be literally `zxcvbn` here.
 */
export interface AnalyzeResponse {
  password_length: number;
  guess_number: number;
  log10_guesses: number;
  strength_score: number;
  strength_label: string;
  indicpass_guesses: number;
  indicpass_score: number;
  baseline_guesses: number | null;
  baseline_score: number | null;
  indicpass: IndicpassBlock;
  matched_patterns: Match[];
  matched_indic_words: number | string[];
  matched_names: number | string[];
  matched_variants: string[];
  estimated_components: Match[];
  warnings: string[];
  combined_log10_guesses?: number;
  pcfg?: PcfgBlock;
  dictionaries: DictionaryInfo[];
  estimators: EstimatorAvailability;
  [key: string]: unknown;
}

export interface AnalyzeRequest {
  password: string;
  reveal_tokens: boolean;
}
