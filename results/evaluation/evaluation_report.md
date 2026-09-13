# Rigorous evaluation -- hin

Generated 2026-09-13T16:09:46+00:00 from IndicPass v0.1.0 at `844cf881d32d`.

This report adds classification, ranking and calibration metrics on top of the frozen research code's own two bounded reference attackers. It computes no guess number, match, PCFG probability or attack rank of its own -- see `docs/evaluation.md`.

## 1. Dataset

1400 generated samples (seed 42), the SAME corpus Milestones 2-5 use. Not a held-out split: the project has no train/dev/test partition of this benchmark, which is why section 6 below reports a diagnostic threshold sweep rather than a selected operating threshold. Categories:

| category | samples |
| --- | ---: |
| english | 200 |
| indic_word | 200 |
| indic_numeric | 200 |
| indic_year | 200 |
| indic_symbol | 200 |
| mixed | 200 |
| random | 200 |

## 2. Ground truth

Two independent bounded attackers, both already part of this project:

* **M4** reference attack (wordlist x rules), version `1.0`. Coverage: 37.7% (528/1400).
* **M5** character attack (reaches out-of-lexicon spellings), version `1.0`. Coverage: 77.9% (1091/1400).

`crackable(B) = covered AND rank <= B`. An attacker that never reached a password contributes 0 to every budget's success count -- never the universe size, never dropped.

## 3. Classification, ranking, at the default budget

Default reporting budget: 10^8 candidates -- one of `config/password.yaml`'s own four pre-existing strength thresholds, fixed independently of this evaluation.

**Ground truth: M4 (wordlist)**

| estimator | n | accuracy | precision | recall | F1 | balanced acc | MCC | ROC-AUC | PR-AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| IndicPass (M2) | 1400 | 0.662 | 0.346 | 1.000 | 0.514 | 0.794 | 0.451 | 0.920 | 0.661 |
| PCFG (M3) | 1400 | 0.669 | 0.337 | 0.884 | 0.488 | 0.753 | 0.389 | 0.835 | 0.409 |
| zxcvbn 4.5.0 | 1400 | 0.522 | 0.261 | 0.916 | 0.406 | 0.676 | 0.279 | 0.775 | 0.426 |

**Ground truth: M5 (character model)**

| estimator | n | accuracy | precision | recall | F1 | balanced acc | MCC | ROC-AUC | PR-AUC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| IndicPass (M2) | 1400 | 0.749 | 0.515 | 1.000 | 0.679 | 0.829 | 0.582 | 0.922 | 0.768 |
| PCFG (M3) | 1400 | 0.776 | 0.545 | 0.960 | 0.695 | 0.835 | 0.593 | 0.941 | 0.846 |
| zxcvbn 4.5.0 | 1400 | 0.639 | 0.424 | 1.000 | 0.596 | 0.754 | 0.465 | 0.868 | 0.593 |

## 4. Attack-budget success rates

Observed (ground truth) success rate -- the fraction of ALL targets an attacker actually cracked within each budget:

| budget | M4 success | M5 success |
| ---: | ---: | ---: |
| 10^3 | 0.8% | 0.2% |
| 10^4 | 3.0% | 1.2% |
| 10^5 | 4.6% | 3.6% |
| 10^6 | 8.9% | 8.9% |
| 10^8 | 17.9% | 26.6% |
| 10^10 | 26.9% | 51.8% |

## 5. Guess-number / rank distributions

`estimated` = a model's own guess number. `observed` = an attack's rank, among the targets it reached. Never averaged together.

| series | n | median log10 | geometric-mean log10 | P10 | P90 |
| --- | ---: | ---: | ---: | ---: | ---: |
| estimated_indicpass | 1400 | 7.84 | 8.01 | 4.24 | 12.79 |
| estimated_pcfg | 1400 | 8.75 | 8.89 | 5.00 | 13.07 |
| estimated_baseline | 1400 | 6.46 | 7.12 | 3.72 | 11.86 |
| observed_m4 | 528 | 8.50 | 8.48 | 4.51 | 13.22 |
| observed_m5 | 1091 | 9.02 | 9.15 | 5.93 | 12.76 |

## 6. Threshold sweep (diagnostic; no threshold is selected)

No held-out development split exists for this frozen benchmark, so per the evaluation protocol, no single threshold below is selected as a recommended operating point -- section 3's budget-anchored classification above is the only frozen, non-tuned operating point this report uses. This table is provided for diagnostic and ROC-construction purposes only, for IndicPass against M4 at the default budget.

| log10 threshold | precision | recall | F1 | accuracy | balanced acc | MCC |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 0 | -- | 0.000 | -- | 0.821 | 0.500 | -- |
| 1 | -- | 0.000 | -- | 0.821 | 0.500 | -- |
| 2 | 1.000 | 0.008 | 0.016 | 0.823 | 0.504 | 0.081 |
| 3 | 1.000 | 0.052 | 0.099 | 0.831 | 0.526 | 0.208 |
| 4 | 0.899 | 0.284 | 0.432 | 0.866 | 0.639 | 0.460 |
| 5 | 0.678 | 0.572 | 0.620 | 0.875 | 0.756 | 0.549 |
| 6 | 0.598 | 0.840 | 0.699 | 0.871 | 0.859 | 0.634 |
| 7 | 0.461 | 0.984 | 0.628 | 0.791 | 0.867 | 0.578 |
| 8 | 0.346 | 1.000 | 0.514 | 0.662 | 0.794 | 0.451 |
| 9 | 0.274 | 1.000 | 0.430 | 0.526 | 0.712 | 0.341 |
| 10 | 0.241 | 1.000 | 0.388 | 0.436 | 0.657 | 0.275 |
| 11 | 0.220 | 1.000 | 0.361 | 0.368 | 0.615 | 0.225 |
| 12 | 0.209 | 1.000 | 0.346 | 0.325 | 0.589 | 0.193 |
| 13 | 0.198 | 1.000 | 0.330 | 0.275 | 0.559 | 0.152 |
| 14 | 0.187 | 1.000 | 0.314 | 0.221 | 0.526 | 0.099 |
| 15 | 0.180 | 1.000 | 0.306 | 0.189 | 0.506 | 0.047 |
| 16 | 0.180 | 1.000 | 0.305 | 0.184 | 0.503 | 0.035 |
| 17 | 0.179 | 1.000 | 0.303 | 0.180 | 0.501 | 0.018 |

## 7. Calibration

This project's guess numbers are not probabilities, so Brier score and Expected Calibration Error are not computed on them -- doing so would require treating a guess count as a probability, which `indicpass.evaluation.metrics` refuses to do (its `brier_score` and `expected_calibration_error` raise on input outside [0, 1]). Both functions exist and are unit-tested against synthetic probabilities.

What IS available and reused unchanged from `indicpass.password.validation.calibration`: an ordinary-least-squares regression of observed log10 rank on predicted log10 guesses. Slope 1 / intercept 0 is perfect calibration against that attack.

| estimator | attacker | n | slope | intercept | r^2 |
| --- | --- | ---: | ---: | ---: | ---: |
| IndicPass (M2) | m4 | 528 | 1.200 | 0.642 | 0.791 |
| IndicPass (M2) | m5 | 1091 | 0.914 | 2.790 | 0.607 |
| PCFG (M3) | m4 | 528 | 0.898 | 1.205 | 0.621 |
| PCFG (M3) | m5 | 1091 | 0.977 | 1.472 | 0.751 |
| zxcvbn 4.5.0 | m4 | 528 | 0.682 | 4.345 | 0.341 |
| zxcvbn 4.5.0 | m5 | 1091 | 0.691 | 4.984 | 0.360 |
| min(M2, zxcvbn) | m4 | 528 | 0.995 | 3.037 | 0.527 |
| min(M2, zxcvbn) | m5 | 1091 | 0.741 | 4.884 | 0.367 |
| min(PCFG, zxcvbn) | m4 | 528 | 0.762 | 3.948 | 0.401 |
| min(PCFG, zxcvbn) | m5 | 1091 | 0.710 | 4.907 | 0.368 |
| min(M2, PCFG, zxcvbn) | m4 | 528 | 0.995 | 3.037 | 0.527 |
| min(M2, PCFG, zxcvbn) | m5 | 1091 | 0.742 | 4.882 | 0.367 |

## 8. Category-wise

At the default budget, ground truth M4, IndicPass only (`category_metrics.csv` carries every estimator and both attackers):

| category | n | accuracy | F1 | ROC-AUC | M4 coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| english | 200 | 0.630 | 0.580 | 0.996 | 60.5% |
| indic_word | 200 | 0.380 | 0.541 | 0.878 | 41.0% |
| indic_numeric | 200 | 0.505 | -- | -- | 46.0% |
| indic_year | 200 | 0.615 | 0.691 | 0.907 | 47.5% |
| indic_symbol | 200 | 0.555 | 0.473 | 0.960 | 49.0% |
| mixed | 200 | 0.950 | -- | -- | 19.5% |
| random | 200 | 1.000 | -- | -- | 0.5% |

By OOV partition (deterministic dictionary-membership classification, not model-derived -- see `indicpass.password.oov.Taxonomy`):

| partition | n | accuracy | F1 | ROC-AUC | M4 coverage |
| --- | ---: | ---: | ---: | ---: | ---: |
| random_control | 200 | 1.000 | -- | -- | 0.5% |
| english_control | 200 | 0.630 | 0.580 | 0.996 | 60.5% |
| mixed_construction | 200 | 0.950 | -- | -- | 19.5% |
| indic_in_lexicon | 332 | 0.723 | 0.812 | 0.950 | 100.0% |
| oov_name | 161 | 0.354 | -- | -- | 9.9% |
| oov_spelling_variant | 134 | 0.440 | -- | -- | 9.0% |
| oov_morphological_variant | 27 | 0.519 | -- | -- | 0.0% |
| oov_stem_suffix | 34 | 0.500 | -- | -- | 20.6% |
| oov_other | 112 | 0.214 | -- | -- | 0.0% |

## 9. Baseline comparison

Same records, same attacker (M4), same default budget:

| metric | IndicPass | PCFG | zxcvbn | IndicPass - zxcvbn | PCFG - zxcvbn |
| --- | ---: | ---: | ---: | ---: | ---: |
| accuracy | 0.662 | 0.669 | 0.522 | +0.140 | +0.147 |
| precision | 0.346 | 0.337 | 0.261 | +0.085 | +0.076 |
| recall | 1.000 | 0.884 | 0.916 | +0.084 | -0.032 |
| f1 | 0.514 | 0.488 | 0.406 | +0.107 | +0.082 |
| roc_auc | 0.920 | 0.835 | 0.775 | +0.145 | +0.060 |
| pr_auc | 0.661 | 0.409 | 0.426 | +0.235 | -0.017 |

## 10. Paired bootstrap (classification statistics)

1000 resamples, percentile method, 95% interval, ground truth M4, default budget. An interval excluding zero is reported as excluding zero; it is not a significance test.

| difference | statistic | value | CI low | CI high | excludes 0 |
| --- | --- | ---: | ---: | ---: | --- |
| indicpass-minus-baseline | accuracy | 0.140 | 0.117 | 0.164 | True |
| indicpass-minus-baseline | f1 | 0.107 | 0.090 | 0.127 | True |
| indicpass-minus-baseline | mcc | 0.172 | 0.140 | 0.207 | True |
| indicpass-minus-baseline | roc_auc | 0.145 | 0.123 | 0.170 | True |
| pcfg-minus-baseline | accuracy | 0.147 | 0.122 | 0.171 | True |
| pcfg-minus-baseline | f1 | 0.082 | 0.059 | 0.106 | True |
| pcfg-minus-baseline | mcc | 0.110 | 0.068 | 0.152 | True |
| pcfg-minus-baseline | roc_auc | 0.060 | 0.038 | 0.084 | True |
| pcfg-minus-indicpass | accuracy | 0.007 | -0.016 | 0.029 | False |
| pcfg-minus-indicpass | f1 | -0.025 | -0.049 | -0.003 | True |
| pcfg-minus-indicpass | mcc | -0.062 | -0.099 | -0.028 | True |
| pcfg-minus-indicpass | roc_auc | -0.085 | -0.096 | -0.074 | True |

## 11. Limitations

* Ground truth is the rank at which ONE of two bounded, fully specified attackers reaches a password -- not a real-world cracking result. Neither attacker uses a leaked-password corpus; see docs/password_strength_design.md sections 15-16.
* The corpus is the SAME generated 1,400-sample benchmark Milestones 2-5 use. It has no held-out development split, so section 6's threshold sweep is diagnostic only; section 3's budget-anchored classification uses config/password.yaml's pre-existing strength thresholds as its only frozen operating points.
* Brier score and Expected Calibration Error are not computed: none of the three estimators outputs a calibrated probability, and indicpass.evaluation.metrics refuses to treat a guess number as one. Regression calibration (slope/intercept against observed rank) is reported instead, reusing indicpass.password.validation.calibration unchanged.
* M4's coverage is conditional: it can rank 0 of 468 out-of-lexicon Indic targets (its universe is a wordlist), so M4-conditioned metrics on that population reflect an all-negative ground truth. M5 exists precisely to cover that population and is reported alongside M4 throughout for exactly this reason.
* Category and partition labels come from the benchmark generator and from indicpass.password.oov.Taxonomy's dictionary-membership rules -- never from an estimator's own prediction.
* This is a synthetic benchmark from a hand-written word bank, not observed passwords. No claim about the distribution of real Indian passwords is supported by anything in this report.

---

Reproducibility self-check: M4 ranks identical across two independent builds: True. M5 ranks identical: True.

