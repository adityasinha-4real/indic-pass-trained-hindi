# Guess-model sensitivity

- **Generated:** 2026-09-07T10:53:43+00:00
- **Git commit:** `8a09173ef35109e4d0310c7a8b118a9afb021f5b`
- **Baseline:** zxcvbn 4.5.0
- **Dictionary:** 297,747 entries, 40,966 priced by measured rank (13.8%)
- **Frequency source:** `wordfreq-3.1.1/hi/small`
- **Corpus:** 1,400 generated samples, seed 42, generator 1.0

Rows are keyed on `sample_id`. **No row maps an id to a password**, and no
composed password -- word plus digits, symbol, year, or any random string --
is written anywhere. The corpus regenerates exactly from the seed above, which
is what reproducibility requires; storing the strings is not.

(Single-word samples are, by construction, the word banks in
`src/indicpass/password/benchmark.py`. Those are committed source and are
printed in the coverage tables on purpose -- they are the measuring instrument.
Seeing a word there discloses nothing about which sample used it.)

## The question

> How much of the shipped configuration's behaviour survives changing the brute-force alphabet assumption, the match-class policy, and the frequency source?

## Brute-force cardinality

Both estimators now charge a flat 10 guesses per unexplained character, so they differ in their lexicon and not in this. The observed_cardinality arm restores the classical alphabet-size model (26/36/95) that IndicPass shipped with in Milestone 1: it was responsible for essentially the whole divergence from the baseline on random controls, where there is no lexical structure to find and therefore nothing the Indic dictionary could have contributed.

## Shipped configuration

| Category | N | IndicPass mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.08 | 7.42 | 2.21 | 60% |
| indic_word | 200 | 4.35 | 4.00 | 1.08 | 44% |
| indic_numeric | 200 | 7.87 | 8.00 | 2.55 | 46% |
| indic_year | 200 | 6.85 | 6.44 | 1.96 | 48% |
| indic_symbol | 200 | 6.98 | 7.00 | 2.12 | 46% |
| mixed | 200 | 11.92 | 12.16 | 3.71 | 78% |
| random | 200 | 11.01 | 11.00 | 3.74 | 1% |

## Effect of each change on mean log10(guesses)

Each cell is the arm's mean minus the shipped configuration's mean, per
category. Positive means the change made passwords look stronger.

| Arm | english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `observed_cardinality` | +1.03 | +1.12 | +1.34 | +1.15 | +2.49 | +3.23 | +7.33 |
| `no_frequency` | +0.04 | +0.42 | +0.44 | +0.46 | +0.46 | +0.63 | +0.00 |
| `no_substring_matches` | +0.56 | +0.07 | +0.79 | +0.91 | +0.93 | +1.82 | +0.00 |
| `no_fragment_matches` | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 |
| `fragment_penalty_1` | +0.00 | -0.00 | -0.03 | -0.01 | -0.01 | -0.02 | -0.03 |
| `min_substring_6` | +0.05 | +0.04 | +0.18 | +0.18 | +0.14 | +0.23 | +0.00 |

## False matches on random controls

500 random strings per cell, seed 42, deterministic.

offered = the matcher found a dictionary span. accepted = one survived into the winning segmentation, so the guess estimate rests on it. Only the second changes an answer; the gap between them is the segmentation search rejecting fragments that are more expensive than calling the span unexplained.

| Alphabet | Length | Offered | mean | median | **Accepted** | mean | median |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| lower | 6 | 79% | 1.71 | 1 | **0%** | 0.00 | 0 |
| lower | 8 | 90% | 2.62 | 2 | **1%** | 0.01 | 0 |
| lower | 10 | 96% | 3.55 | 3 | **1%** | 0.01 | 0 |
| lower | 12 | 98% | 4.71 | 4 | **0%** | 0.00 | 0 |
| lower | 14 | 99% | 5.31 | 5 | **1%** | 0.01 | 0 |
| alnum | 6 | 56% | 1.06 | 1 | **0%** | 0.00 | 0 |
| alnum | 8 | 66% | 1.49 | 1 | **0%** | 0.00 | 0 |
| alnum | 10 | 77% | 2.02 | 2 | **1%** | 0.01 | 0 |
| alnum | 12 | 85% | 2.58 | 2 | **0%** | 0.00 | 0 |
| alnum | 14 | 90% | 3.00 | 3 | **0%** | 0.00 | 0 |
| full | 6 | 47% | 0.79 | 0 | **0%** | 0.00 | 0 |
| full | 8 | 55% | 0.99 | 1 | **0%** | 0.00 | 0 |
| full | 10 | 62% | 1.39 | 1 | **0%** | 0.00 | 0 |
| full | 12 | 70% | 1.57 | 1 | **0%** | 0.00 | 0 |
| full | 14 | 74% | 1.81 | 1 | **0%** | 0.00 | 0 |

Worst accepted rate across all cells: **1.2%**.

### Effect of the fragment policy on false matches

| Configuration | Worst accepted rate |
| --- | ---: |
| shipped (fragment penalty 10x) | 1.2% |
| fragments priced as words | 3.2% |
| fragments dropped entirely | 0.6% |

## What each arm is

| Arm | What it changes |
| --- | --- |
| `observed_cardinality` | Brute-force alphabet taken from the character classes present (26/36/95) instead of the shipped flat 10. The Milestone 1 policy, and the one that made the whole random-control divergence. |
| `no_frequency` | The Milestone 1 pricing: provenance tier only, no observed frequency. Isolates what the external frequency table bought. |
| `no_substring_matches` | Only whole-password dictionary hits count. The strictest reading of 'prefer exact matches'. |
| `no_fragment_matches` | Sub-threshold hits dropped rather than penalised. |
| `fragment_penalty_1` | Fragments priced identically to real words -- the uncorrected behaviour the class penalty exists to fix. |
| `min_substring_6` | The substring threshold raised from 4 to 6, where a random hit has probability 2e-4 rather than 0.055. |

### `observed_cardinality`

| Category | N | observed_cardinality mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 8.11 | 7.94 | 2.48 | 94% |
| indic_word | 200 | 5.47 | 5.66 | 1.41 | 61% |
| indic_numeric | 200 | 9.22 | 9.04 | 3.00 | 70% |
| indic_year | 200 | 7.99 | 8.29 | 2.48 | 74% |
| indic_symbol | 200 | 9.47 | 9.25 | 2.98 | 76% |
| mixed | 200 | 15.15 | 15.36 | 3.87 | 100% |
| random | 200 | 18.34 | 17.91 | 4.00 | 16% |

### `no_frequency`

| Category | N | no_frequency mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.12 | 7.48 | 2.19 | 62% |
| indic_word | 200 | 4.77 | 4.63 | 1.17 | 32% |
| indic_numeric | 200 | 8.31 | 8.00 | 2.77 | 31% |
| indic_year | 200 | 7.31 | 7.37 | 2.19 | 36% |
| indic_symbol | 200 | 7.44 | 7.00 | 2.33 | 37% |
| mixed | 200 | 12.55 | 12.96 | 3.82 | 70% |
| random | 200 | 11.02 | 11.00 | 3.75 | 0% |

### `no_substring_matches`

| Category | N | no_substring_matches mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.64 | 8.00 | 2.56 | 26% |
| indic_word | 200 | 4.42 | 4.00 | 1.15 | 34% |
| indic_numeric | 200 | 8.66 | 8.60 | 3.01 | 0% |
| indic_year | 200 | 7.76 | 7.43 | 2.43 | 0% |
| indic_symbol | 200 | 7.91 | 8.00 | 2.63 | 0% |
| mixed | 200 | 13.75 | 14.00 | 3.94 | 0% |
| random | 200 | 11.02 | 11.00 | 3.75 | 0% |

### `no_fragment_matches`

| Category | N | no_fragment_matches mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.08 | 7.42 | 2.21 | 60% |
| indic_word | 200 | 4.35 | 4.00 | 1.08 | 44% |
| indic_numeric | 200 | 7.87 | 8.00 | 2.55 | 46% |
| indic_year | 200 | 6.85 | 6.44 | 1.96 | 47% |
| indic_symbol | 200 | 6.98 | 7.00 | 2.12 | 46% |
| mixed | 200 | 11.92 | 12.16 | 3.71 | 78% |
| random | 200 | 11.02 | 11.00 | 3.75 | 0% |

### `fragment_penalty_1`

| Category | N | fragment_penalty_1 mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.08 | 7.42 | 2.21 | 60% |
| indic_word | 200 | 4.35 | 4.00 | 1.08 | 44% |
| indic_numeric | 200 | 7.85 | 8.00 | 2.55 | 48% |
| indic_year | 200 | 6.84 | 6.44 | 1.96 | 48% |
| indic_symbol | 200 | 6.97 | 7.00 | 2.11 | 46% |
| mixed | 200 | 11.90 | 12.16 | 3.71 | 79% |
| random | 200 | 10.98 | 11.00 | 3.73 | 4% |

### `min_substring_6`

| Category | N | min_substring_6 mean log10 | median log10 | mean score | match rate |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.12 | 7.42 | 2.23 | 55% |
| indic_word | 200 | 4.39 | 4.00 | 1.10 | 40% |
| indic_numeric | 200 | 8.06 | 8.00 | 2.67 | 32% |
| indic_year | 200 | 7.03 | 6.49 | 2.08 | 40% |
| indic_symbol | 200 | 7.12 | 7.00 | 2.19 | 40% |
| mixed | 200 | 12.16 | 12.44 | 3.75 | 70% |
| random | 200 | 11.01 | 11.00 | 3.74 | 1% |

