# Mined-tier ablation

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

> Is the mined tier -- the largest and least precise source -- carrying the result, or is it adding noise?

The mined tier is 120,000 of the dictionary's 297,747 entries, automatically
extracted from monolingual and parallel corpora. Only ~2% of it has an observed
corpus frequency, so almost all of it is priced by the tier fallback -- and a
fallback-priced hit is a policy, not a measurement.

## Arms

| Arm | What it is |
| --- | --- |
| `indicpass` | The shipped configuration. Every other arm is this with one thing changed. |
| `no_mined_tier` | Ablation D: the mined tier dropped. It is the largest and least precise source, and a result that rests on it is a result about corpus noise. |
| `no_dictionary` | Ablation B: the same meter with an empty dictionary. Isolates what the Indic lexicon contributes from what generic pattern scoring does. |

## Effect on the estimate

| Category | All tiers | Without mined | Difference | Without any dictionary |
| --- | ---: | ---: | ---: | ---: |
| english | 7.08 | 7.09 | +0.01 | 8.26 |
| indic_word | 4.35 | 4.36 | +0.00 | 5.21 |
| indic_numeric | 7.87 | 7.90 | +0.03 | 8.66 |
| indic_year | 6.85 | 6.89 | +0.04 | 7.76 |
| indic_symbol | 6.98 | 7.02 | +0.04 | 7.91 |
| mixed | 11.92 | 11.96 | +0.04 | 13.75 |
| random | 11.01 | 11.01 | -0.00 | 11.02 |

## Match rates

| Category | Match rate, all tiers | Match rate, without mined |
| --- | ---: | ---: |
| english | 60% | 60% |
| indic_word | 44% | 42% |
| indic_numeric | 46% | 44% |
| indic_year | 48% | 42% |
| indic_symbol | 46% | 42% |
| mixed | 78% | 74% |
| random | 1% | 1% |

## Comparison against the baseline, with and without the mined tier

| Category | Mean diff, all tiers | Mean diff, without mined |
| --- | ---: | ---: |
| english | +3.19 | +3.21 |
| indic_word | +0.11 | +0.12 |
| indic_numeric | +0.78 | +0.81 |
| indic_year | +0.33 | +0.37 |
| indic_symbol | -0.00 | +0.03 |
| mixed | +1.78 | +1.82 |
| random | +0.05 | +0.04 |

