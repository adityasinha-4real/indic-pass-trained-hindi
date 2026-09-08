# Password benchmark -- IndicPass vs zxcvbn

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

> Does explicit Romanized-Indic lexical modelling reduce estimated guess counts for Romanized Indic passwords, relative to a generic estimator?

Hypothesis categories: `indic_word`, `indic_numeric`, `indic_year`, `indic_symbol`. Controls: `english`, `random`.

## Comparison by category

`Difference` is mean log10(IndicPass) - mean log10(zxcvbn). **Negative means
IndicPass estimates fewer guesses.** Lower is not automatically more accurate:
that would require a reference attack model, which this project does not have.

| Category | N | IndicPass median log10 | zxcvbn median log10 | Median diff | Mean diff | IP lower | IP higher | equal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.42 | 4.11 | +3.00 | +3.19 | 0 | 200 | 0 |
| indic_word | 200 | 4.00 | 4.01 | +0.00 | +0.11 | 60 | 75 | 65 |
| indic_numeric | 200 | 8.00 | 7.00 | +0.62 | +0.78 | 39 | 129 | 32 |
| indic_year | 200 | 6.44 | 6.11 | +0.43 | +0.33 | 53 | 143 | 4 |
| indic_symbol | 200 | 7.00 | 7.00 | +0.00 | -0.00 | 63 | 83 | 54 |
| mixed | 200 | 12.16 | 10.12 | +1.95 | +1.78 | 34 | 162 | 4 |
| random | 200 | 11.00 | 11.00 | +0.00 | +0.05 | 2 | 18 | 180 |

## What the Indic lexicon adds to the baseline

The table above asks whether IndicPass *beats* zxcvbn, which is the wrong
question: IndicPass has no common-password wordlist and was never going to win
outright on English. The question the experiment actually poses is whether the
Indic lexicon carries information the generic estimator lacks.

Guessing cost is a minimum over the attacker's options, so an attacker holding
both wordlists pays `min(IndicPass, zxcvbn)`. **Information added** is that
minimum minus zxcvbn alone: how much cheaper the password becomes once Indic
lexical knowledge is available. It is never positive, and it is zero exactly
when IndicPass found nothing the baseline had not already found.

| Category | zxcvbn alone | min(IndicPass, zxcvbn) | Information added (mean) | (median) | Samples improved |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 3.88 | 3.88 | +0.00 | +0.00 | 0/200 |
| indic_word | 4.24 | 3.87 | -0.37 | +0.00 | 60/200 |
| indic_numeric | 7.09 | 6.84 | -0.25 | +0.00 | 39/200 |
| indic_year | 6.52 | 6.19 | -0.33 | +0.00 | 53/200 |
| indic_symbol | 6.98 | 6.50 | -0.48 | +0.00 | 63/200 |
| mixed | 10.14 | 9.87 | -0.27 | +0.00 | 34/200 |
| random | 10.97 | 10.96 | -0.00 | +0.00 | 2/200 |

## Strength scores

| Category | IndicPass mean | zxcvbn mean | IndicPass median | zxcvbn median | Disagreements |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 2.21 | 0.74 | 2.0 | 1.0 | 189/200 |
| indic_word | 1.08 | 0.95 | 1.0 | 1.0 | 62/200 |
| indic_numeric | 2.55 | 2.04 | 3.0 | 2.0 | 125/200 |
| indic_year | 1.96 | 1.93 | 2.0 | 2.0 | 89/200 |
| indic_symbol | 2.12 | 1.92 | 2.0 | 2.0 | 101/200 |
| mixed | 3.71 | 3.33 | 4.0 | 4.0 | 90/200 |
| random | 3.74 | 3.42 | 4.0 | 4.0 | 64/200 |

## Ablation A/B -- the Indic dictionary

Ablation A vs B: the same meter with and without the Indic dictionary. The difference is what the lexicon contributes; the remainder is generic pattern scoring that any estimator would do.

| Category | With dictionary | Without | Effect of the lexicon |
| --- | ---: | ---: | ---: |
| english | 7.08 | 8.26 | -1.18 |
| indic_word | 4.35 | 5.21 | -0.86 |
| indic_numeric | 7.87 | 8.66 | -0.79 |
| indic_year | 6.85 | 7.76 | -0.91 |
| indic_symbol | 6.98 | 7.91 | -0.93 |
| mixed | 11.92 | 13.75 | -1.82 |
| random | 11.01 | 11.02 | -0.00 |

## Match rates

How often the dictionary contributed at all, and how often the hit was priced
by a measured rank rather than a provenance-tier fallback.

| Category | Any dictionary hit | Hit priced by measured rank |
| --- | ---: | ---: |
| english | 60% | 40% |
| indic_word | 44% | 38% |
| indic_numeric | 46% | 42% |
| indic_year | 48% | 44% |
| indic_symbol | 46% | 42% |
| mixed | 78% | 68% |
| random | 1% | 1% |

## Overall

1,400 samples, mean log10 8.01, median 7.84.

*Mixes seven populations whose proportions are an artefact of the generator. Read the per-category table instead.*

