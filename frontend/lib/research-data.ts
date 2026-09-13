/**
 * Frozen research results, transcribed for display.
 *
 * Every number below is copied verbatim from a committed report under
 * `results/reports/`, `results/evaluation/`, or from
 * `docs/password_strength_design.md` — this file computes nothing. It exists
 * because those reports are Markdown/JSON meant for a research audience, and
 * this frontend needs the same numbers as typed React data with a citation
 * attached to each group, so a reviewer-facing page can render them without
 * asking the backend to re-derive anything.
 *
 * If a milestone is re-run and a report changes, this file goes stale and
 * must be re-transcribed by hand — there is no live link. That trade-off is
 * deliberate: `docs/evaluation.md` and `password_strength_design.md` are the
 * authoritative documents, and this file is a presentational copy of a
 * frozen snapshot of them, not a second source of truth.
 *
 * SVG figures referenced here are static copies of the committed research
 * artefacts, published for the frontend to embed directly (see
 * `frontend/public/research/`):
 *   - `public/research/figures/*.svg` <- `results/figures/*.svg`
 *     (Milestone 5's own report figures — all evaluate the character
 *     attack; several also compare M5's coverage against M4's)
 *   - `public/research/evaluation-figures/*.svg` <- `results/evaluation/figures/*.svg`
 *     (the classifier-style evaluation layer, ground truth = M4, budget 10^8
 *     unless a figure's own title says otherwise)
 * The SVGs themselves are byte-for-byte copies, not regenerated — this
 * project's own scoring/attack/evaluation code renders them, never this
 * frontend.
 */

// ---------------------------------------------------------------------------
// Dictionary & coverage
// Source: results/reports/indicdict_coverage_hin.md
// ---------------------------------------------------------------------------

export const DICTIONARY_SCALE = {
  totalEntries: 297_747,
  frequencyRankedEntries: 40_966,
  frequencyCoveragePct: 13.8,
  frequencySource: "wordfreq-3.1.1/hi/small",
  tiers: [
    { name: "human_romanized", entries: 30_400, ranked: 13_437, unranked: 16_963 },
    { name: "curated_entities", entries: 25_005, ranked: 1_747, unranked: 23_258 },
    { name: "curated_other", entries: 122_342, ranked: 23_612, unranked: 98_730 },
    { name: "mined", entries: 120_000, ranked: 2_170, unranked: 117_830 },
  ],
  source: "results/reports/indicdict_coverage_hin.md",
} as const;

export const DICTIONARY_COVERAGE = {
  // "Full bank": 163 hand-written Hindi probe words from benchmark.py's
  // INDIC_WORDS, checked for dictionary membership -- not sampled from the
  // dictionary itself.
  fullBank: { words: 163, present: 62, absent: 101, coveragePct: 38.0 },
  coreBrief: { words: 15, present: 8, absent: 7, coveragePct: 53.3 },
  englishControls: { words: 10, present: 7, absent: 3, coveragePct: 70.0 },
  missingCommonWords: [
    "namaste", "namaskar", "dhanyavaad", "maa", "ghar", "dost", "bhai", "ram",
    "sita", "sharma", "rahul", "india", "zindagi",
  ],
  contaminationNote:
    "English-control coverage (70%) is higher than the Indic probe bank's (38%). Words like " +
    "“password”, “football”, “dragon” and “superman” are present " +
    "in IndicDict as accidental transliteration-corpus overlap, not because the dictionary targets English " +
    "vocabulary. This is a confound the English-category benchmark results must be read against.",
  source: "results/reports/indicdict_coverage_hin.md",
} as const;

// zxcvbn's own bundled wordlists already contain several common Indic words
// -- pinned by tests/test_baseline.py. "Indic word => invisible to zxcvbn" is
// false; the real finding (see M4_VALIDATION below) is that zxcvbn's ranking
// of bare Romanized Hindi words carries almost no information, not that it
// never matches one.
export const ZXCVBN_CONTAMINATION = {
  wordsZxcvbnAlreadyKnows: ["namaste", "bharat", "krishna", "sharma"],
  source: "docs/password_strength_design.md §9 (\"[measured]\" note); tests/test_baseline.py",
} as const;

// ---------------------------------------------------------------------------
// Representative case studies
// Source: docs/password_strength_design.md §5.3 ("Worked examples") and §4.3
// (the namaste case) and §12 / §9 for the zxcvbn comparison numbers.
// These are the project's own worked examples against the committed
// dictionary -- not cherry-picked for this dashboard.
// ---------------------------------------------------------------------------

export interface CaseStudy {
  password: string;
  structure: string;
  indicpassGuesses: string;
  indicpassLog10: number;
  score: number;
  zxcvbnNote?: string;
  significance: string;
}

export const CASE_STUDIES: CaseStudy[] = [
  {
    password: "bharat",
    structure: "One dictionary word (भारत, rank 41 by measured frequency).",
    indicpassGuesses: "42",
    indicpassLog10: 1.62,
    score: 0,
    significance:
      "भारत is one of the commonest words in Hindi. Frequency-ranked pricing (not just " +
      "dictionary membership) is what drives the guess number this low -- under tier-only pricing (no " +
      "frequency data) the same word costs 42,904 guesses instead of ~41.",
  },
  {
    password: "bharat2024",
    structure: "Dictionary word + year: WORD(bharat) + YEAR(2024).",
    indicpassGuesses: "21,152",
    indicpassLog10: 4.33,
    score: 1,
    significance:
      "2! × (41 × 136) + 10,000 = 21,152. The year window (136 candidates for a bounded year " +
      "range) and the segment-order factorial are the same combinatorics zxcvbn itself uses; only the " +
      "word's price (41 vs. zxcvbn treating “bharat” as unrecognised) differs.",
  },
  {
    password: "merabharat",
    structure: "Two dictionary words: WORD(mera) + WORD(bharat).",
    indicpassGuesses: "27,466",
    indicpassLog10: 4.44,
    score: 1,
    significance:
      "2! × (213 × 41) + 10,000 = 27,466. Two of the commonest words in the language, composed " +
      "— exactly the construction a generic English-only wordlist has no path to recognising at all.",
  },
  {
    password: "krishna123",
    structure: "Dictionary word (mined tier, lower frequency) + 3 digits.",
    indicpassGuesses: "6,062,000",
    indicpassLog10: 6.78,
    score: 2,
    significance:
      "2! × (3,026 × 1,000) + 10,000 = 6,062,000. कृष्णा ranks 3,026th " +
      "by measured frequency — present and priced, but far less common than “bharat”, which is " +
      "exactly the kind of frequency spread a flat dictionary-membership check cannot represent.",
  },
  {
    password: "namaste",
    structure: "No dictionary hit survives — priced as a fully unexplained 7-character span.",
    indicpassGuesses: "10,000,000",
    indicpassLog10: 7.0,
    score: 2,
    zxcvbnNote: "zxcvbn: 3,847 guesses (it is in zxcvbn's bundled English wordlist)",
    significance:
      "The project's own documented worst case. “namaste” is absent from IndicDict at source " +
      "(Aksharantar's Hindi split never contains it), so IndicPass falls back to the brute-force floor " +
      "(10^7) while zxcvbn, which happens to carry it as an English dictionary word, scores it far lower. " +
      "The gap is a coverage gap in the 297,747-entry dictionary, not an arithmetic error — stated " +
      "plainly in docs/password_strength_design.md §4.3 rather than hidden.",
  },
];

export const CASE_STUDY_SOURCE = "docs/password_strength_design.md §5.3, §4.3, §9";

// ---------------------------------------------------------------------------
// M4 — reference (wordlist x rules) attack validation
// Source: results/reports/reference_attack_hin.md
// ---------------------------------------------------------------------------

export const M4_ATTACK = {
  universeLog10: 15.85,
  universeExact: "7,115,868,421,625,340",
  budgetLog10: 16,
  lexicon: "IndicDict, 297,747 spellings, ordered by frequency",
  rulesPlaced: 63,
  coveragePct: 37.7,
  coveredOfTotal: "528 / 1400",
  ovlOfLexiconCoveragePct: 0.0,
  ovlOfLexiconOf: "0 / 872 (out-of-lexicon targets are structurally unreachable by a wordlist attack)",
  source: "results/reports/reference_attack_hin.md",
} as const;

export interface EstimatorValidationRow {
  estimator: string;
  n: number;
  spearman: number;
  pearson: number;
  meanErr: number;
  mae: number;
  rmse: number;
  within1_0: number; // fraction within +-1.0 log10 of the observed rank
  calibrationSlope: number;
  calibrationIntercept: number;
  calibrationR2: number;
}

export const M4_VALIDATION: EstimatorValidationRow[] = [
  { estimator: "IndicPass (M2)", n: 528, spearman: 0.900, pearson: 0.889, meanErr: -1.951, mae: 1.955, rmse: 2.440, within1_0: 0.263, calibrationSlope: 1.200, calibrationIntercept: 0.642, calibrationR2: 0.791 },
  { estimator: "PCFG (M3)", n: 528, spearman: 0.806, pearson: 0.788, meanErr: -0.377, mae: 1.370, rmse: 1.934, within1_0: 0.502, calibrationSlope: 0.898, calibrationIntercept: 1.205, calibrationR2: 0.621 },
  { estimator: "zxcvbn 4.5.0", n: 528, spearman: 0.592, pearson: 0.584, meanErr: -2.417, mae: 2.828, rmse: 3.558, within1_0: 0.140, calibrationSlope: 0.682, calibrationIntercept: 4.345, calibrationR2: 0.341 },
];

// zxcvbn's rank correlation restricted to the indic_word category alone --
// the number the frontend previously quoted as "0.005" in isolation. Kept
// with its category context here rather than repeated as a bare headline.
export const ZXCVBN_INDIC_WORD_SPEARMAN = 0.005;

// ---------------------------------------------------------------------------
// M5 — out-of-lexicon character-model attack validation
// Source: results/reports/milestone5_oov_attack.md
// ---------------------------------------------------------------------------

export const M5_ATTACK = {
  universeStemsLog10: 22.53,
  budgetCandidates: "10^16",
  characterModel: "order-3, Laplace alpha=1.0, trained on all 297,747 IndicDict spellings",
  coveragePct: 77.9,
  coveredOfTotal: "1091 / 1400",
  oovIndicCoveragePct: 100.0,
  oovIndicCoveredOf: "468 / 468",
  source: "results/reports/milestone5_oov_attack.md",
} as const;

export const M5_VALIDATION_ALL: EstimatorValidationRow[] = [
  { estimator: "IndicPass (M2)", n: 1091, spearman: 0.764, pearson: 0.779, meanErr: -2.194, mae: 2.214, rmse: 2.756, within1_0: 0.276, calibrationSlope: 0.914, calibrationIntercept: 2.790, calibrationR2: 0.607 },
  { estimator: "PCFG (M3)", n: 1091, spearman: 0.851, pearson: 0.867, meanErr: -1.293, mae: 1.471, rmse: 1.847, within1_0: 0.377, calibrationSlope: 0.977, calibrationIntercept: 1.472, calibrationR2: 0.751 },
  { estimator: "zxcvbn 4.5.0", n: 1091, spearman: 0.591, pearson: 0.600, meanErr: -3.122, mae: 3.138, rmse: 3.835, within1_0: 0.152, calibrationSlope: 0.691, calibrationIntercept: 4.984, calibrationR2: 0.360 },
];

// The 468 out-of-lexicon Indic targets: the population Milestone 3's
// character model exists for. This is the project's central trade-off:
// M2 orders better, M3 gets the magnitude closer -- both hold up under a
// paired bootstrap on the SAME targets. Calibration slope/r^2 here are the
// "oov_indic" rows from §6's confidence-interval tables (calibration
// intercept is not broken out per-population in that section, so it is
// omitted rather than reused from a different population).
export const M5_OOV_INDIC_VALIDATION: EstimatorValidationRow[] = [
  { estimator: "IndicPass (M2)", n: 468, spearman: 0.919, pearson: 0.917, meanErr: -1.094, mae: 1.128, rmse: 1.397, within1_0: 0.498, calibrationSlope: 1.005, calibrationIntercept: NaN, calibrationR2: 0.841 },
  { estimator: "PCFG (M3)", n: 468, spearman: 0.858, pearson: 0.878, meanErr: -0.684, mae: 1.037, rmse: 1.274, within1_0: 0.528, calibrationSlope: 0.882, calibrationIntercept: NaN, calibrationR2: 0.770 },
  { estimator: "zxcvbn 4.5.0", n: 468, spearman: 0.772, pearson: 0.744, meanErr: -1.982, mae: 2.003, rmse: 2.463, within1_0: 0.244, calibrationSlope: 0.914, calibrationIntercept: NaN, calibrationR2: 0.554 },
];

export interface PairedBootstrapRow {
  population: string;
  n: number;
  rhoM2: number;
  rhoM3: number;
  rhoDiffLow: number;
  rhoDiffHigh: number;
  maeM2: number;
  maeM3: number;
  maeDiffLow: number;
  maeDiffHigh: number;
}

// M3 minus M2, on the SAME targets, paired 2000-resample bootstrap, 95% CI.
export const M5_M3_VS_M2_TRADEOFF: PairedBootstrapRow = {
  population: "oov_indic (out-of-lexicon Indic targets)",
  n: 468,
  rhoM2: 0.919,
  rhoM3: 0.858,
  rhoDiffLow: -0.078,
  rhoDiffHigh: -0.044, // excludes zero -> M2 orders better here
  maeM2: 1.128,
  maeM3: 1.037,
  maeDiffLow: -0.141,
  maeDiffHigh: -0.042, // excludes zero -> M3 calibrates better here
};

export const OOV_SEPARATION = {
  medianLog10RankInLexicon: 9.18,
  medianLog10RankOovIndic: 8.14,
  medianLog10RankRandomControl: 14.62,
  separationOrdersOfMagnitude: 6.49,
  source: "results/reports/milestone5_oov_attack.md §8.1",
} as const;

// ---------------------------------------------------------------------------
// PCFG character-model generalisation
// Source: results/reports/pcfg_benchmark_hin.md ("What the character model
// learned")
// ---------------------------------------------------------------------------

export const PCFG_GENERALIZATION = {
  inDictLog10PerChar: 0.935,
  inDictN: 62,
  oovLog10PerChar: 0.936,
  oovN: 101,
  randomControlLog10PerChar: 2.204,
  floorLog10PerChar: 1.000,
  marginOverFloor: 0.064,
  source: "results/reports/pcfg_benchmark_hin.md",
} as const;

// ---------------------------------------------------------------------------
// Classifier-style evaluation layer (uncommitted at the time of writing;
// functionally complete, self-consistent with the frozen M2-M5 milestones)
// Source: results/evaluation/evaluation_report.md, results/evaluation/metrics.json
// ---------------------------------------------------------------------------

export const EVAL_DEFAULT_BUDGET = "10^8 guesses"; // config/password.yaml's own pre-existing threshold

export interface ClassificationRow {
  estimator: string;
  accuracy: number;
  precision: number;
  recall: number;
  f1: number;
  balancedAccuracy: number;
  mcc: number;
  rocAuc: number;
  prAuc: number;
}

export const CLASSIFICATION_M4: ClassificationRow[] = [
  { estimator: "IndicPass (M2)", accuracy: 0.662, precision: 0.346, recall: 1.000, f1: 0.514, balancedAccuracy: 0.794, mcc: 0.451, rocAuc: 0.920, prAuc: 0.661 },
  { estimator: "PCFG (M3)", accuracy: 0.669, precision: 0.337, recall: 0.884, f1: 0.488, balancedAccuracy: 0.753, mcc: 0.389, rocAuc: 0.835, prAuc: 0.409 },
  { estimator: "zxcvbn 4.5.0", accuracy: 0.522, precision: 0.261, recall: 0.916, f1: 0.406, balancedAccuracy: 0.676, mcc: 0.279, rocAuc: 0.775, prAuc: 0.426 },
];

export const CLASSIFICATION_M5: ClassificationRow[] = [
  { estimator: "IndicPass (M2)", accuracy: 0.749, precision: 0.515, recall: 1.000, f1: 0.679, balancedAccuracy: 0.829, mcc: 0.582, rocAuc: 0.922, prAuc: 0.768 },
  { estimator: "PCFG (M3)", accuracy: 0.776, precision: 0.545, recall: 0.960, f1: 0.695, balancedAccuracy: 0.835, mcc: 0.593, rocAuc: 0.941, prAuc: 0.846 },
  { estimator: "zxcvbn 4.5.0", accuracy: 0.639, precision: 0.424, recall: 1.000, f1: 0.596, balancedAccuracy: 0.754, mcc: 0.465, rocAuc: 0.868, prAuc: 0.593 },
];

// IndicPass's confusion matrix at the default budget, ground truth = M4 --
// read directly off results/evaluation/figures/confusion_matrix.svg's own
// labelled values (tp=250, fn=0, fp=473, tn=677), cross-checked against
// accuracy/precision/recall in the table above.
export const CONFUSION_MATRIX_M4_INDICPASS = {
  truePositive: 250,
  falseNegative: 0,
  falsePositive: 473,
  trueNegative: 677,
  n: 1400,
} as const;

export const BASELINE_DELTA = {
  // IndicPass minus zxcvbn, same records, same attacker (M4), same budget.
  accuracy: 0.140,
  precision: 0.085,
  recall: 0.084,
  f1: 0.107,
  rocAuc: 0.145,
  prAuc: 0.235,
  source: "results/evaluation/evaluation_report.md §9",
} as const;

export interface BootstrapDiffRow {
  comparison: string;
  statistic: string;
  value: number;
  ciLow: number;
  ciHigh: number;
  excludesZero: boolean;
}

// 1000-resample paired percentile bootstrap, 95% CI, ground truth M4,
// default budget.
export const CLASSIFICATION_BOOTSTRAP: BootstrapDiffRow[] = [
  { comparison: "IndicPass − zxcvbn", statistic: "accuracy", value: 0.140, ciLow: 0.117, ciHigh: 0.164, excludesZero: true },
  { comparison: "IndicPass − zxcvbn", statistic: "F1", value: 0.107, ciLow: 0.090, ciHigh: 0.127, excludesZero: true },
  { comparison: "IndicPass − zxcvbn", statistic: "MCC", value: 0.172, ciLow: 0.140, ciHigh: 0.207, excludesZero: true },
  { comparison: "IndicPass − zxcvbn", statistic: "ROC-AUC", value: 0.145, ciLow: 0.123, ciHigh: 0.170, excludesZero: true },
  { comparison: "PCFG − IndicPass", statistic: "ROC-AUC", value: -0.085, ciLow: -0.096, ciHigh: -0.074, excludesZero: true },
  { comparison: "PCFG − IndicPass", statistic: "accuracy", value: 0.007, ciLow: -0.016, ciHigh: 0.029, excludesZero: false },
];

export const EVAL_SOURCE = "results/evaluation/evaluation_report.md (uncommitted at time of writing; see Provenance note)";

// ---------------------------------------------------------------------------
// Attack-budget success rates
// Source: results/evaluation/evaluation_report.md §4
// ---------------------------------------------------------------------------

export interface AttackBudgetRow {
  log10Budget: number;
  budgetLabel: string;
  m4SuccessPct: number;
  m5SuccessPct: number;
}

export const ATTACK_BUDGET: AttackBudgetRow[] = [
  { log10Budget: 3, budgetLabel: "10³", m4SuccessPct: 0.8, m5SuccessPct: 0.2 },
  { log10Budget: 4, budgetLabel: "10⁴", m4SuccessPct: 3.0, m5SuccessPct: 1.2 },
  { log10Budget: 5, budgetLabel: "10⁵", m4SuccessPct: 4.6, m5SuccessPct: 3.6 },
  { log10Budget: 6, budgetLabel: "10⁶", m4SuccessPct: 8.9, m5SuccessPct: 8.9 },
  { log10Budget: 8, budgetLabel: "10⁸", m4SuccessPct: 17.9, m5SuccessPct: 26.6 },
  { log10Budget: 10, budgetLabel: "10¹⁰", m4SuccessPct: 26.9, m5SuccessPct: 51.8 },
];

// ---------------------------------------------------------------------------
// Category & OOV-partition breakdown
// Source: results/evaluation/evaluation_report.md §8; results/reports/milestone5_oov_attack.md §2
// ---------------------------------------------------------------------------

export interface CategoryRow {
  name: string;
  n: number;
  accuracy: number;
  f1?: number;
  rocAuc?: number;
  m4CoveragePct: number;
}

export const CATEGORY_BREAKDOWN: CategoryRow[] = [
  { name: "english", n: 200, accuracy: 0.630, f1: 0.580, rocAuc: 0.996, m4CoveragePct: 60.5 },
  { name: "indic_word", n: 200, accuracy: 0.380, f1: 0.541, rocAuc: 0.878, m4CoveragePct: 41.0 },
  { name: "indic_numeric", n: 200, accuracy: 0.505, m4CoveragePct: 46.0 },
  { name: "indic_year", n: 200, accuracy: 0.615, f1: 0.691, rocAuc: 0.907, m4CoveragePct: 47.5 },
  { name: "indic_symbol", n: 200, accuracy: 0.555, f1: 0.473, rocAuc: 0.960, m4CoveragePct: 49.0 },
  { name: "mixed", n: 200, accuracy: 0.950, m4CoveragePct: 19.5 },
  { name: "random", n: 200, accuracy: 1.000, m4CoveragePct: 0.5 },
];

export const OOV_PARTITION_BREAKDOWN: CategoryRow[] = [
  { name: "random_control", n: 200, accuracy: 1.000, m4CoveragePct: 0.5 },
  { name: "english_control", n: 200, accuracy: 0.630, f1: 0.580, rocAuc: 0.996, m4CoveragePct: 60.5 },
  { name: "mixed_construction", n: 200, accuracy: 0.950, m4CoveragePct: 19.5 },
  { name: "indic_in_lexicon", n: 332, accuracy: 0.723, f1: 0.812, rocAuc: 0.950, m4CoveragePct: 100.0 },
  { name: "oov_name", n: 161, accuracy: 0.354, m4CoveragePct: 9.9 },
  { name: "oov_spelling_variant", n: 134, accuracy: 0.440, m4CoveragePct: 9.0 },
  { name: "oov_morphological_variant", n: 27, accuracy: 0.519, m4CoveragePct: 0.0 },
  { name: "oov_stem_suffix", n: 34, accuracy: 0.500, m4CoveragePct: 20.6 },
  { name: "oov_other", n: 112, accuracy: 0.214, m4CoveragePct: 0.0 },
];

// Per-category rank correlation against the M4/M5 observed attack order --
// the ranking-quality companion to the classification accuracy table above.
// Source: results/reports/reference_attack_hin.md §3.1 (M4, "IndicPass (M2)"
// row per category) and results/reports/milestone5_oov_attack.md §4.5.
export const CATEGORY_SPEARMAN_M4: Record<string, number> = {
  english: 0.868,
  indic_word: 0.694,
  indic_numeric: 0.844,
  indic_year: 0.602,
  indic_symbol: 0.849,
  mixed: 0.874,
};

export const ZXCVBN_CATEGORY_SPEARMAN_M4: Record<string, number> = {
  english: 0.677,
  indic_word: 0.005,
  indic_numeric: 0.109,
  indic_year: 0.251,
  indic_symbol: 0.509,
  mixed: 0.596,
};

// ---------------------------------------------------------------------------
// Reproducibility
// Source: results/reports/reproducibility.md
// ---------------------------------------------------------------------------

export const REPRODUCIBILITY = {
  identicalReports: 8,
  totalReports: 8,
  seed: 42,
  experiments: [
    { name: "coverage", wallClockSeconds: 10 },
    { name: "benchmark", wallClockSeconds: 103 },
    { name: "pcfg", wallClockSeconds: 466 },
    { name: "reference_attack", wallClockSeconds: 129 },
    { name: "oov_attack", wallClockSeconds: 530 },
  ],
  method:
    "Every pipeline run twice, in two separate processes, each writing to its own directory; the two " +
    "reports compared byte-for-byte after removing only the generation timestamp.",
  source: "results/reports/reproducibility.md",
} as const;

// ---------------------------------------------------------------------------
// Limitations — restated from the project's own documentation, not softened
// Source: docs/password_strength_design.md (multiple sections), milestone5_oov_attack.md §10-11,
// evaluation_report.md §11
// ---------------------------------------------------------------------------

export const LIMITATIONS: string[] = [
  "Dictionary coverage is 38.0% on the project's own 163-word Hindi probe bank (53.3% on the smaller " +
    "core-brief subset). A word the dictionary does not hold cannot be recognised however good the " +
    "scoring is — this is the ceiling on every Indic-category result in this dashboard.",
  "zxcvbn's bundled wordlists already contain some Indic words (“namaste”, “bharat”, " +
    "“krishna”, “sharma” among them). “Indic word” does not mean “invisible " +
    "to zxcvbn” — the measured finding is that zxcvbn's ranking of bare Romanized Hindi words " +
    "carries almost no ordering information (Spearman 0.005), not that it never matches one.",
  "Leetspeak and character-substitution mangling (e.g. “p@ssw0rd”-style substitutions) are not " +
    "implemented in IndicPass or in its reference attacks — documented as unimplemented in three " +
    "separate module docstrings. No comparison data for this exists, and none is claimed here.",
  "Mixed/Hinglish results are nuanced, not a clean win: the raw estimate on the “mixed” category " +
    "can be higher for IndicPass than zxcvbn, but the “information added” by the Indic lexicon " +
    "specifically (isolating the dictionary's contribution) is still measured as slightly negative on " +
    "that category in the frozen benchmark.",
  "Both reference attacks (M4, M5) are fully specified, bounded, reproducible procedures defined by this " +
    "project — not real leaked-password data. No claim here is validated against an observed " +
    "real-world password distribution.",
  "M4 (wordlist attack) has 0% coverage of the 468 out-of-lexicon Indic targets by construction — a " +
    "wordlist cannot reach a spelling it does not contain. M5 exists specifically to cover that " +
    "population and is reported alongside M4 throughout for this reason.",
  "The benchmark corpus (1,400 samples) is synthetic — generated from hand-written word banks, not " +
    "collected or observed passwords — and there is no held-out development split of it. The " +
    "classifier-evaluation thresholds use config/password.yaml's pre-existing, non-tuned strength bands " +
    "rather than a threshold fit on this data.",
  "The 9-way out-of-lexicon partition (name / spelling-variant / morphological-variant / stem-suffix / " +
    "other) is a mechanical classification heuristic, not a linguistic claim, and will mislabel some " +
    "targets. The exact in-lexicon/out-of-lexicon split it refines is precise dictionary membership.",
  "No fusion estimator combining M2's ordering with M3's calibration is shipped. Fitting one would " +
    "require a labelled corpus disjoint from this same 1,400-sample evaluation benchmark, which does not " +
    "exist — fitting and evaluating on the same data would measure the generator, not a real " +
    "improvement.",
];

// ---------------------------------------------------------------------------
// The project's own stated central claim, quoted verbatim.
// ---------------------------------------------------------------------------

export const CORE_CLAIM =
  "For Romanized Indic passwords, an Indic-aware estimator predicts a bounded reference attacker's " +
  "ordering substantially better than a generic one does, and the two Indic estimators trade off against " +
  "each other: the lexical model orders better, the probabilistic model calibrates better.";

export const CORE_CLAIM_SOURCE = "docs/password_strength_design.md §17.4";

// ---------------------------------------------------------------------------
// Provenance note for the classifier-evaluation layer specifically.
// ---------------------------------------------------------------------------

export const EVAL_PROVENANCE = {
  generatedAt: "2026-09-13T16:09:46Z",
  gitCommit: "844cf881d32d",
  note:
    "This evaluation layer (docs/evaluation.md, the metrics/bootstrap/figure code under " +
    "src/indicpass/evaluation/, and everything under results/evaluation/) is complete and self-consistent " +
    "with the frozen M2-M5 milestones, but was not yet committed to version control as of this " +
    "dashboard update. It reuses M2-M5's own guess numbers, matches and attack ranks unchanged and " +
    "computes no new guess number, match, or attack rank of its own.",
} as const;
