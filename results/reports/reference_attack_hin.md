# Reference-attack validation -- hin

Generated 2026-09-07T17:38:52+00:00 from IndicPass v0.1.0 at `8a09173ef351`.

This report scores three estimators against an **observed** cracking order. That order is a fact about one specific attacker, defined below and reproducible from it. It is **not** a real-world cracking result: no leaked password corpus is used anywhere in this project, and no claim of real-world accuracy is made or supported here.

## 1. The reference attack

Attack version `1.0`, fingerprint `sha256:7d01bfe5fd530263772...`

| setting | value |
| --- | --- |
| lexicon | IndicDict, 297,747 spellings |
| lexicon order | `frequency` (40,966 placed by observed frequency, 13.8%) |
| rule order | `size` |
| rules placed | 63 (3 dropped by budget) |
| budget | 10^16 candidates |
| universe enumerated | 7,115,868,421,625,340 = 10^15.85 |
| digits / symbol+digits | up to 5 / 3 |
| years | 1940-2029 |
| symbols | 14 (`!@#$%^&*()-_.+`) |
| combinator (word+word) | True |
| seed | 42 |

The first ten rule blocks, in enumeration order:

| # | rule | block size | candidates before it |
| --- | --- | ---: | ---: |
| 1 | `word/lower` | 297,747 | 0 |
| 2 | `word/capitalized` | 297,747 | 297,747 |
| 3 | `word/upper` | 297,747 | 595,494 |
| 4 | `word+digits1/lower` | 2,977,470 | 893,241 |
| 5 | `word+digits1/capitalized` | 2,977,470 | 3,870,711 |
| 6 | `word+digits1/upper` | 2,977,470 | 6,848,181 |
| 7 | `word+symbol/lower` | 4,168,458 | 9,825,651 |
| 8 | `word+symbol/capitalized` | 4,168,458 | 13,994,109 |
| 9 | `word+symbol/upper` | 4,168,458 | 18,162,567 |
| 10 | `word+year/lower` | 26,797,230 | 22,331,025 |

Dropped by the budget: `word+word+digits5/lower`, `word+word+digits5/capitalized`, `word+word+digits5/upper`.

## 2. Coverage

An uncovered password is given **no rank**. It is never assigned the universe size, a censored bound, or any substituted value, and it contributes to this table and to nothing else.

| category | targets | covered | coverage | median log10 rank | mean log10 rank |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 121 | 60.5% | 8.52 | 7.98 |
| indic_word | 200 | 82 | 41.0% | 5.32 | 5.11 |
| indic_numeric | 200 | 92 | 46.0% | 9.39 | 9.54 |
| indic_year | 200 | 95 | 47.5% | 7.55 | 8.06 |
| indic_symbol | 200 | 98 | 49.0% | 10.06 | 9.25 |
| mixed | 200 | 39 | 19.5% | 14.56 | 13.61 |
| random | 200 | 1 | 0.5% | 11.14 | 11.14 |
| **all** | 1400 | 528 | 37.7% | 8.50 | 8.48 |

The two families that are not benchmark categories -- case variation and unseen spellings -- are strata over the same 1,400 samples, because both are properties of the attacker's lexicon or of the generator's case roll rather than of a category:

| stratum | targets | covered | coverage | median log10 rank |
| --- | ---: | ---: | ---: | ---: |
| case_variation | 453 | 191 | 42.2% | 7.80 |
| unseen_spelling | 872 | 0 | 0.0% | -- |
| in_lexicon | 528 | 528 | 100.0% | 8.50 |

## 3. Estimators against the observed rank

`error = predicted log10 guesses - observed log10 rank`. **Positive means the estimator called the password stronger than this attack found it** -- the dangerous direction for a meter.

| estimator | n | Spearman | Pearson | mean err | median err | MAE | med abs | RMSE | +-0.5 | +-1.0 | direction |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| IndicPass (M2) | 528 | 0.900 | 0.889 | -1.951 | -1.857 | 1.955 | 1.857 | 2.440 | 17.1% | 26.3% | under-estimates |
| PCFG (M3) | 528 | 0.806 | 0.788 | -0.377 | -0.057 | 1.370 | 0.994 | 1.934 | 29.2% | 50.2% | calibrated |
| zxcvbn 4.5.0 | 528 | 0.592 | 0.584 | -2.417 | -2.073 | 2.828 | 2.197 | 3.558 | 5.7% | 14.0% | under-estimates |
| min(M2, zxcvbn) | 528 | 0.734 | 0.726 | -3.011 | -2.481 | 3.014 | 2.481 | 3.670 | 6.8% | 9.1% | under-estimates |
| min(PCFG, zxcvbn) | 528 | 0.638 | 0.633 | -2.529 | -2.073 | 2.748 | 2.104 | 3.513 | 6.4% | 16.3% | under-estimates |
| min(M2, PCFG, zxcvbn) | 528 | 0.734 | 0.726 | -3.011 | -2.481 | 3.014 | 2.481 | 3.670 | 6.8% | 9.1% | under-estimates |

Which estimator wins under each metric -- reported as a table rather than a ranking, because they disagree and the disagreement is a result:

| metric | winner | value |
| --- | --- | ---: |
| spearman | IndicPass (M2) | 0.900 |
| pearson | IndicPass (M2) | 0.889 |
| mean_absolute_error | PCFG (M3) | 1.370 |
| median_absolute_error | PCFG (M3) | 0.994 |
| rmse | PCFG (M3) | 1.934 |
| within_0.5_log10 | PCFG (M3) | 0.292 |
| within_1.0_log10 | PCFG (M3) | 0.502 |
| abs_mean_signed_error | PCFG (M3) | 0.377 |

### 3.1 By category

| category | estimator | n | Spearman | mean err | MAE | +-1.0 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| english | IndicPass (M2) | 121 | 0.868 | -1.467 | 1.467 | 62.0% |
|  | PCFG (M3) | 121 | 0.723 | -0.105 | 1.714 | 33.9% |
|  | zxcvbn 4.5.0 | 121 | 0.677 | -4.227 | 4.227 | 1.7% |
| indic_word | IndicPass (M2) | 82 | 0.694 | -1.310 | 1.332 | 52.4% |
|  | PCFG (M3) | 82 | 0.558 | -0.293 | 1.524 | 30.5% |
|  | zxcvbn 4.5.0 | 82 | 0.005 | -0.814 | 2.047 | 39.0% |
| indic_numeric | IndicPass (M2) | 92 | 0.844 | -2.082 | 2.082 | 5.4% |
|  | PCFG (M3) | 92 | 0.560 | -0.504 | 1.079 | 63.0% |
|  | zxcvbn 4.5.0 | 92 | 0.109 | -2.417 | 2.598 | 16.3% |
| indic_year | IndicPass (M2) | 95 | 0.602 | -1.838 | 1.839 | 11.6% |
|  | PCFG (M3) | 95 | 0.531 | -0.152 | 0.834 | 83.2% |
|  | zxcvbn 4.5.0 | 95 | 0.251 | -1.558 | 2.015 | 12.6% |
| indic_symbol | IndicPass (M2) | 98 | 0.849 | -2.707 | 2.707 | 2.0% |
|  | PCFG (M3) | 98 | 0.669 | -1.090 | 1.524 | 46.9% |
|  | zxcvbn 4.5.0 | 98 | 0.509 | -2.156 | 2.545 | 11.2% |
| mixed | IndicPass (M2) | 39 | 0.874 | -2.834 | 2.837 | 7.7% |
|  | PCFG (M3) | 39 | 0.799 | +0.218 | 1.533 | 41.0% |
|  | zxcvbn 4.5.0 | 39 | 0.596 | -2.897 | 3.347 | 5.1% |
| random | IndicPass (M2) | 1 | -- | -3.143 | 3.143 | 0.0% |
|  | PCFG (M3) | 1 | -- | -3.143 | 3.143 | 0.0% |
|  | zxcvbn 4.5.0 | 1 | -- | -3.143 | 3.143 | 0.0% |

### 3.2 By stratum

| stratum | estimator | n | Spearman | mean err | MAE | +-1.0 |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| case_variation | IndicPass (M2) | 191 | 0.908 | -2.121 | 2.122 | 14.7% |
|  | PCFG (M3) | 191 | 0.843 | -0.611 | 1.249 | 58.6% |
|  | zxcvbn 4.5.0 | 191 | 0.651 | -2.434 | 2.666 | 11.5% |
| unseen_spelling | IndicPass (M2) | 0 | -- | +0.000 | 0.000 | 0.0% |
|  | PCFG (M3) | 0 | -- | +0.000 | 0.000 | 0.0% |
|  | zxcvbn 4.5.0 | 0 | -- | +0.000 | 0.000 | 0.0% |
| in_lexicon | IndicPass (M2) | 528 | 0.900 | -1.951 | 1.955 | 26.3% |
|  | PCFG (M3) | 528 | 0.806 | -0.377 | 1.370 | 50.2% |
|  | zxcvbn 4.5.0 | 528 | 0.592 | -2.417 | 2.828 | 14.0% |

## 4. Calibration

Ordinary least squares of observed `log10` rank on predicted `log10` guesses. Slope 1 and intercept 0 is perfect calibration **against this attack**. A slope below one means the estimator spreads passwords over fewer orders of magnitude than the attack does.

| estimator | n | slope | intercept | r^2 |
| --- | ---: | ---: | ---: | ---: |
| IndicPass (M2) | 528 | 1.200 | 0.642 | 0.791 |
| PCFG (M3) | 528 | 0.898 | 1.205 | 0.621 |
| zxcvbn 4.5.0 | 528 | 0.682 | 4.345 | 0.341 |
| min(M2, zxcvbn) | 528 | 0.995 | 3.037 | 0.527 |
| min(PCFG, zxcvbn) | 528 | 0.762 | 3.948 | 0.401 |
| min(M2, PCFG, zxcvbn) | 528 | 0.995 | 3.037 | 0.527 |

Bias by decile of prediction, for the three primary estimators. `bias = mean predicted - mean observed`:

**IndicPass (M2)**

| decile | n | predicted range | mean predicted | mean observed | bias |
| ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 52 | 1.62-3.66 | 3.21 | 4.03 | -0.82 |
| 2 | 52 | 3.75-4.42 | 4.09 | 5.46 | -1.37 |
| 3 | 52 | 4.46-5.12 | 4.80 | 6.30 | -1.51 |
| 4 | 52 | 5.12-5.77 | 5.44 | 7.34 | -1.90 |
| 5 | 52 | 5.77-6.32 | 6.06 | 8.35 | -2.29 |
| 6 | 52 | 6.39-7.00 | 6.67 | 8.99 | -2.32 |
| 7 | 52 | 7.00-7.57 | 7.25 | 9.62 | -2.37 |
| 8 | 52 | 7.59-8.08 | 7.86 | 9.38 | -1.52 |
| 9 | 52 | 8.10-8.94 | 8.39 | 10.69 | -2.30 |
| 10 | 52 | 8.95-12.54 | 10.42 | 13.61 | -3.19 |
| 11 | 8 | 12.84-15.31 | 13.63 | 15.08 | -1.45 |

**PCFG (M3)**

| decile | n | predicted range | mean predicted | mean observed | bias |
| ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 52 | 2.72-4.94 | 4.15 | 4.32 | -0.18 |
| 2 | 52 | 4.94-6.00 | 5.40 | 4.91 | +0.49 |
| 3 | 52 | 6.00-6.75 | 6.19 | 7.34 | -1.15 |
| 4 | 52 | 6.75-7.21 | 6.99 | 8.35 | -1.36 |
| 5 | 52 | 7.21-8.00 | 7.57 | 7.54 | +0.03 |
| 6 | 52 | 8.00-8.43 | 8.08 | 8.55 | -0.47 |
| 7 | 52 | 8.58-9.00 | 8.96 | 9.98 | -1.02 |
| 8 | 52 | 9.00-10.00 | 9.55 | 9.73 | -0.18 |
| 9 | 52 | 10.00-11.00 | 10.11 | 10.83 | -0.72 |
| 10 | 52 | 11.00-16.00 | 12.54 | 12.23 | +0.30 |
| 11 | 8 | 16.00-21.49 | 17.72 | 14.98 | +2.74 |

**zxcvbn 4.5.0**

| decile | n | predicted range | mean predicted | mean observed | bias |
| ---: | ---: | --- | ---: | ---: | ---: |
| 1 | 52 | 0.48-2.50 | 1.79 | 5.76 | -3.97 |
| 2 | 52 | 2.67-4.00 | 3.48 | 5.87 | -2.40 |
| 3 | 52 | 4.01-4.95 | 4.38 | 6.58 | -2.20 |
| 4 | 52 | 4.95-5.52 | 5.17 | 8.31 | -3.15 |
| 5 | 52 | 5.52-5.87 | 5.69 | 8.84 | -3.15 |
| 6 | 52 | 5.87-6.15 | 6.03 | 8.52 | -2.49 |
| 7 | 52 | 6.16-6.99 | 6.48 | 9.62 | -3.14 |
| 8 | 52 | 7.00-8.00 | 7.43 | 9.28 | -1.86 |
| 9 | 52 | 8.00-9.00 | 8.37 | 9.84 | -1.47 |
| 10 | 52 | 9.00-12.76 | 10.55 | 11.34 | -0.78 |
| 11 | 8 | 12.76-18.89 | 14.27 | 13.87 | +0.40 |

The `points` array in the JSON carries thinned `(predicted, observed)` pairs for plotting. A pair of numbers identifies no password.

## 5. Does the answer depend on the attacker?

Each arm is the attack above with exactly one thing changed. The `frequency` arm shares its wordlist ordering with IndicPass and the PCFG; `shuffled` and `length` share nothing. **A conclusion is only safe where the arms agree.**

| arm | independent | coverage | log10 universe | Spearman M2 / PCFG / zxcvbn | MAE M2 / PCFG / zxcvbn |
| --- | --- | ---: | ---: | --- | --- |
| `frequency` | NO | 37.7% | 15.85 | 0.900 / 0.806 / 0.592 | 1.95 / 1.37 / 2.83 |
| `shuffled` | yes | 37.7% | 15.85 | 0.885 / 0.793 / 0.590 | 2.20 / 1.32 / 2.96 |
| `length` | yes | 37.7% | 15.85 | 0.890 / 0.809 / 0.605 | 2.16 / 1.26 / 2.90 |
| `family_rules` | NO | 37.7% | 15.85 | 0.812 / 0.716 / 0.559 | 2.19 / 1.56 / 3.02 |
| `budget_1e12` | NO | 32.9% | 11.58 | 0.866 / 0.783 / 0.558 | 1.66 / 1.09 / 2.37 |
| `no_combinator` | NO | 30.5% | 11.05 | 0.918 / 0.875 / 0.714 | 1.47 / 0.92 / 2.07 |

* **`frequency`** -- Wordlist ordered by observed corpus frequency. SHARES EVIDENCE with IndicPass and the PCFG: both are built on the same wordfreq table.
* **`shuffled`** -- The same spellings in seeded-shuffle order. No estimator has an informational advantage. The independence arm.
* **`length`** -- Shortest word first, then alphabetical. Frequency-free but not random, so it separates 'no frequency' from 'no information'.
* **`family_rules`** -- Rules ordered by a human-written family precedence instead of by ascending block size. Does the conclusion depend on the rule order?
* **`budget_1e12`** -- A thousand times smaller attack budget. What does a cheaper attacker stop being able to reach?
* **`no_combinator`** -- word+word rules removed. Isolates how much of the multi-word category's rank comes from the combinator attack.

## 6. Controls

### 6.1 Random

The attack reaches **1 of 200** random controls (0.5%). The lexicon can produce the leading letter run of 1 of the 200 at all.

The attack should reach almost no random string: its rules are a wordlist crossed with short suffixes, and a random string is not that. A high number here would mean the lexicon is matching noise and would invalidate every rank in the table above.

### 6.2 Leakage and independence

| the candidate generator uses ... | |
| --- | --- |
| IndicPass scores | False |
| PCFG probabilities | False |
| zxcvbn scores | False |

* src/indicpass/password/reference_attack.py imports NOTHING but the standard library -- not the meter, scoring, matcher, baseline or pcfg, and not even the dictionary.
* tests/test_reference_attack.py parses that module's imports, asserts the set is stdlib-only, and fails on any estimator module appearing in it.
* tests/test_reference_attack.py also ranks a corpus with the meter, the PCFG and the baseline replaced by objects that raise on any attribute access, and asserts the ranks are unchanged.
* scripts/reference_attack.py scores every password before any attack object exists, and reuses those predictions unchanged across all arms.

**Partial independence.** Mechanically complete. Evidentially partial: under lexicon_order=frequency the attacker's wordlist order comes from the same wordfreq table IndicPass prices words with and the PCFG's word distribution is built from. That arm therefore FAVOURS those two estimators by construction. The shuffled and length arms remove the shared evidence.

### 6.3 Reproducibility

| quantity | identical across two independent builds |
| --- | --- |
| lexicon fingerprint | True |
| attack fingerprint | True |
| block programme | True |
| every target rank | True (1400 targets) |
| aggregate metrics | True |

Attack fingerprint: `sha256:7d01bfe5fd530263772863a802cd875f5e340e0228197e37f3b6b413f488af02`

### 6.4 Selection

528 covered, 872 uncovered. Every metric is computed on COVERED targets only. An uncovered password has no observed rank and is given none. The covered set is therefore exactly the set this attack can reach, and the metrics are conditional on that -- they say how well an estimator predicts the attack WHERE THE ATTACK WORKS, not how well it predicts passwords in general.

## 7. How to read this

* observed reference rank is a fact about ONE attacker; estimated guess number is a model output. The two are never the same quantity and are never averaged together.
* A positive signed error means the estimator called a password STRONGER than this attack found it. That is the dangerous direction.
* The frequency arm shares its wordlist ordering evidence with IndicPass and the PCFG. A result that appears only there is a statement about shared evidence, not about estimator quality.
* Nothing here licenses a claim about real-world cracking accuracy. This attack has no leaked-password list, no Markov or PCFG guess generator, no leet substitution, no keyboard walks and no targeted personal data.

---

Corpus: 1400 generated samples, generator version 1.0, seed 42. No password is stored in this report; rows are keyed on `sample_id` and the corpus regenerates from committed source and that seed.

