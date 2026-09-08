# PCFG benchmark -- IndicPass PCFG vs zxcvbn

- **Generated:** 2026-09-07T14:02:37+00:00
- **Git commit:** `8a09173ef35109e4d0310c7a8b118a9afb021f5b`
- **Baseline:** zxcvbn 4.5.0
- **Dictionary:** 297,747 entries, 40,966 with an observed frequency (13.8%)
- **Frequency source:** `wordfreq-3.1.1/hi/small`
- **Grammar:** order-4 character model, geometric(q=0.5) segment prior truncated at 8, uniform category prior
- **Guess curve:** 200,000 sampled derivations, seed 42, 1328 stored points
- **Dictionary fingerprint:** `sha256:9e17fb7da40a0622...`
- **Corpus:** 1,400 generated samples, seed 42, generator 1.0

Rows are keyed on `sample_id`. **No row maps an id to a password**, and no
composed password -- word plus digits, symbol, year, or any random string --
is written anywhere. The corpus regenerates exactly from the seed above.

> **The PCFG is a model, not a measurement of attacker behaviour.** Nothing
> here has been validated against an observed cracking run. "Estimates fewer
> guesses" is a statement about two models, not about reality.

## The question

> Does a probabilistic grammar over Romanized-Indic password structure carry information a generic estimator lacks, without inventing structure in strings that have none?

Hypothesis categories: `indic_word`, `indic_numeric`, `indic_year`, `indic_symbol`. Controls: `english`, `random`.

## Three estimators, same passwords, same call

| Category | N | Milestone 2 median | **PCFG median** | zxcvbn median |
| --- | ---: | ---: | ---: | ---: |
| english | 200 | 7.42 | **8.00** | 4.11 |
| indic_word | 200 | 4.00 | **4.94** | 4.01 |
| indic_numeric | 200 | 8.00 | **8.79** | 7.00 |
| indic_year | 200 | 6.44 | **8.00** | 6.11 |
| indic_symbol | 200 | 7.00 | **7.64** | 7.00 |
| mixed | 200 | 12.16 | **14.00** | 10.12 |
| random | 200 | 11.00 | **11.00** | 11.00 |

## PCFG against zxcvbn

`Difference` is mean log10(PCFG) - mean log10(zxcvbn). **Negative means the
PCFG estimates fewer guesses.**

| Category | N | PCFG mean | zxcvbn mean | Mean diff | Median diff | PCFG lower | PCFG higher | equal |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 7.96 | 3.88 | +4.07 | +3.93 | 0 | 200 | 0 |
| indic_word | 200 | 4.82 | 4.24 | +0.58 | +0.31 | 20 | 112 | 68 |
| indic_numeric | 200 | 8.69 | 7.09 | +1.59 | +1.23 | 3 | 156 | 41 |
| indic_year | 200 | 8.34 | 6.52 | +1.82 | +1.90 | 13 | 187 | 0 |
| indic_symbol | 200 | 7.84 | 6.98 | +0.85 | +0.37 | 7 | 122 | 71 |
| mixed | 200 | 13.62 | 10.14 | +3.47 | +3.62 | 3 | 192 | 5 |
| random | 200 | 11.02 | 10.97 | +0.05 | -0.00 | 0 | 18 | 182 |

## What the grammar adds to the baseline

Guessing cost is a minimum over the attacker's options, so an attacker holding
both models pays `min(PCFG, zxcvbn)`. **Information added** is that minimum
minus zxcvbn alone. It is never positive, and it is zero exactly when the PCFG
found nothing zxcvbn had not already found.

| Category | zxcvbn alone | min(PCFG, zxcvbn) | Information added | Improved |
| --- | ---: | ---: | ---: | ---: |
| english | 3.88 | 3.88 | +0.00 | 0/200 |
| indic_word | 4.24 | 4.11 | -0.13 | 20/200 |
| indic_numeric | 7.09 | 7.08 | -0.01 | 3/200 |
| indic_year | 6.52 | 6.42 | -0.10 | 13/200 |
| indic_symbol | 6.98 | 6.95 | -0.03 | 7/200 |
| mixed | 10.14 | 10.13 | -0.02 | 3/200 |
| random | 10.97 | 10.97 | -0.00 | 0/200 |

### All three together

`min(Milestone 2, PCFG, zxcvbn)` -- the deployable object, since an attacker
holds every model they can get.

| Category | min of all three | Information added vs zxcvbn | Improved |
| --- | ---: | ---: | ---: |
| english | 3.88 | +0.00 | 0/200 |
| indic_word | 3.87 | -0.37 | 62/200 |
| indic_numeric | 6.84 | -0.25 | 39/200 |
| indic_year | 6.19 | -0.33 | 53/200 |
| indic_symbol | 6.50 | -0.48 | 63/200 |
| mixed | 9.87 | -0.27 | 34/200 |
| random | 10.96 | -0.00 | 2/200 |

## PCFG against the Milestone 2 estimator

Not a claim that either is right. The two price the same evidence differently:
Milestone 2 charges a wordlist position and multiplies by heuristic factors;
the PCFG charges a normalised probability, which includes paying for the
*structure* choice that the Milestone 2 model gets for free.

| Category | Milestone 2 mean | PCFG mean | Difference |
| --- | ---: | ---: | ---: |
| english | 7.08 | 7.96 | +0.88 |
| indic_word | 4.35 | 4.82 | +0.46 |
| indic_numeric | 7.87 | 8.69 | +0.81 |
| indic_year | 6.85 | 8.34 | +1.49 |
| indic_symbol | 6.98 | 7.84 | +0.86 |
| mixed | 11.92 | 13.62 | +1.69 |
| random | 11.01 | 11.02 | +0.00 |

## What the grammar actually derived

The category sequence of the winning derivation, per category. Shape only --
no content. `floor` is how often the brute-force floor, rather than the
grammar, produced the reported number; `unsupported` how often no derivation
covered the password at all.

| Category | Commonest derivations | word segment | floor | unsupported |
| --- | --- | ---: | ---: | ---: |
| english | `unknown+digits` 28%, `unknown` 25%, `word` 25% | 47% | 77% | 0% |
| indic_word | `unknown` 69%, `word` 31% | 31% | 69% | 0% |
| indic_numeric | `unknown+digits` 61%, `word+digits` 38%, `unknown+year` 0% | 38% | 90% | 0% |
| indic_year | `unknown+year` 62%, `word+year` 38% | 38% | 20% | 0% |
| indic_symbol | `unknown+symbols+digits` 32%, `unknown+symbols` 30%, `word+symbols+digits` 20% | 38% | 92% | 0% |
| mixed | `unknown+symbols+digits` 20%, `unknown+word` 10%, `unknown` 10% | 57% | 91% | 0% |
| random | `unknown+unknown` 14%, `unknown+unknown+unknown` 12%, `unknown+unknown+unknown+unknown` 5% | 4% | 100% | 3% |

## What the character model learned

Cost is -log10 P per character; lower means the model finds the text likelier. The dictionary-present and dictionary-absent rows are the generalisation test: if they match, the model learned the shape of the language rather than its vocabulary. The floor row is the bar any of it has to clear before it can change a reported estimate.

| Population | N | log10 cost per character |
| --- | ---: | ---: |
| indic bank in dictionary | 62 | 0.935 |
| indic bank absent from dictionary | 101 | 0.936 |
| english control | 76 | 1.047 |
| random lowercase | 500 | 2.204 |
| **the brute-force floor** | -- | **1.000** |

Two readings, and the second is the one that explains the benchmark.

1. **The model generalised.** Bank words the dictionary is *missing* cost 0.936 per character against 0.935 for words it trained on. Those are the same number: it learned the shape of Romanized Hindi, not a list of spellings. Random strings cost 2.204, so the discrimination is real and large.

2. **The margin over the floor is not.** Only the gap between the model and the floor can ever reach a reported estimate, and that gap is +0.064 log10 per character on unseen Hindi -- a fraction of an order of magnitude on a whole word, and less than the structure and category priors charge for using the category at all. This is why the `no_character_model` ablation moves nothing, and it is a fact about the flat-10 floor Milestone 2 adopted rather than about the character model.

## The random control

The control that decides whether any Indic result is believable. A grammar
that also lowered random strings would be finding structure that is not there,
and the Indic effect would be the same artefact.

word_rate is how often the winning derivation contains a dictionary segment; below_bruteforce_rate is how often the grammar alone priced a random string below enumerating it. The second is the one that could change an estimate. A model that read random strings as cheaper than brute force would be inventing structure, and every Indic result would have to be read as the same artefact.

300 random strings per cell, seed 42, deterministic.

| Alphabet | Length | Derivation contains a word | Grammar below brute force | Mean grammar - brute force |
| --- | ---: | ---: | ---: | ---: |
| lower | 6 | 2% | **0.0%** | +7.85 |
| lower | 8 | 1% | **0.0%** | +10.33 |
| lower | 10 | 3% | **0.0%** | +13.09 |
| lower | 12 | 2% | **0.0%** | +15.79 |
| lower | 14 | 4% | **0.0%** | +18.34 |
| alnum | 6 | 0% | **0.0%** | +10.54 |
| alnum | 8 | 1% | **0.0%** | +14.38 |
| alnum | 10 | 3% | **0.0%** | +17.34 |
| alnum | 12 | 1% | **0.0%** | +inf |
| alnum | 14 | 2% | **0.0%** | +inf |
| full | 6 | 0% | **0.0%** | +12.89 |
| full | 8 | 2% | **0.0%** | +16.60 |
| full | 10 | 0% | **0.0%** | +inf |
| full | 12 | 1% | **0.0%** | +inf |
| full | 14 | 2% | **0.0%** | +inf |

Worst cell: 4% of random strings had a dictionary segment in the winning derivation, and **0.0%** were priced below enumerating them.

## Ablations

Each arm is the shipped configuration with exactly one thing changed, fitted
from scratch -- grammar **and** guess curve, because a curve built for one
grammar says nothing about another. Cells are the arm's mean log10 minus the
shipped configuration's, per category. Positive means the change made
passwords look stronger.

| Arm | english | indic_word | indic_numeric | indic_year | indic_symbol | mixed | random |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `no_bruteforce_floor` | +1.46 | +0.67 | +2.08 | +0.07 | +2.50 | +3.05 | +inf |
| `no_character_model` | -0.02 | +0.01 | -0.01 | +0.14 | -0.02 | +0.00 | +0.00 |
| `no_dictionary` | +0.29 | +0.36 | +0.07 | +0.52 | +0.07 | +0.13 | +0.00 |
| `segments_0.3` | -0.02 | -0.03 | -0.00 | +0.03 | +0.01 | -0.00 | +0.00 |
| `segments_0.7` | +0.02 | +0.03 | +0.00 | +0.01 | -0.00 | +0.01 | +0.00 |
| `category_lexical` | -0.06 | -0.09 | -0.01 | +0.25 | +0.00 | -0.04 | +0.00 |
| `curve_seed_7` | +0.00 | +0.00 | +0.00 | +0.00 | -0.00 | -0.00 | +0.00 |
| `ngram_order_3` | -0.00 | +0.01 | -0.00 | +0.09 | -0.00 | +0.01 | +0.00 |
| `ngram_order_5` | -0.04 | -0.05 | +0.00 | -0.12 | +0.00 | -0.03 | +0.00 |
| `ngram_curated_only` | -0.00 | -0.01 | -0.00 | -0.03 | -0.00 | -0.01 | +0.00 |
| `unranked_uniform` | -0.01 | +0.00 | +0.01 | +0.03 | +0.00 | -0.01 | +0.00 |
| `unranked_excluded` | +0.04 | +0.05 | -0.00 | +0.01 | +0.01 | +0.04 | +0.00 |

| Arm | What it changes |
| --- | --- |
| `no_bruteforce_floor` | The grammar's own number, with min(grammar, brute force) turned off. Isolates what the retained non-PCFG floor is doing -- on the random controls, everything. |
| `no_character_model` | The `unknown` category removed, so only dictionary words, digits, years and symbols can derive a span. This is the PCFG WITHOUT the character n-gram: it isolates the component added to address Milestone 2's coverage ceiling. |
| `no_dictionary` | The `word` category removed. Everything alphabetic must go through the character model. Isolates the lexicon from the shape model -- the two halves of the Indic claim. |
| `segments_0.3` | Structure prior with q=0.3 instead of 0.5: multi-segment passwords are assumed rarer. An ASSUMPTION arm -- no data chose 0.5 either. |
| `segments_0.7` | Structure prior with q=0.7: multi-segment passwords assumed commoner. The other side of the same assumption. |
| `category_lexical` | Category prior skewed towards lexical segments (word 0.40, unknown 0.30, digits 0.15, symbols 0.10, year 0.05) instead of uniform. Plausible, and measured by nothing -- which is exactly why it is an arm and not the default. It bounds what the maximum-entropy choice costs. |
| `curve_seed_7` | The same grammar with the guess curve re-sampled from a different seed. Not a design choice: this bounds the Monte-Carlo estimator's own variance, so a reader can tell a real effect from sampling noise. |
| `ngram_order_3` | A shorter character model. Less context, more backoff. |
| `ngram_order_5` | A longer character model. More context, sparser counts. |
| `ngram_curated_only` | The character model trained without the 120,000-entry mined tier, which is the least precise source and the one Milestone 2 had to clear of carrying its result. |
| `unranked_uniform` | Entries with no observed frequency weighted alike across tiers instead of by their tier's measured coverage. |
| `unranked_excluded` | Entries with no observed frequency dropped from the word category entirely -- 86% of the dictionary -- leaving the character model to explain them. |

---

*A lower estimate is NOT automatically a more accurate one. Establishing that needs a reference attack -- a cracking run against a real leak -- which this project does not have. These numbers state the direction and the magnitude and stop there.*

