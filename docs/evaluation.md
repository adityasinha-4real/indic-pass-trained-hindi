# Rigorous evaluation

A measurement layer over the frozen password-strength research code. This
document covers `src/indicpass/evaluation/` and `scripts/evaluate_model.py`
only — everything under `src/indicpass/password/`, `config/`, `data/`,
`models/`, `results/reports/` and the rest of `tests/` is unchanged and is
documented elsewhere (`docs/password_strength_design.md`,
`docs/architecture.md`).

**This is a measurement layer, not a second research pipeline.** It trains no
model, tunes no threshold, retimes no attack and changes no config value. Every
number it reports is either read from a call to the existing
`IndicPassMeter.score()`, or from the existing `ReferenceAttack`/
`CharacterAttack` objects, computed exactly the way
`scripts/reference_attack.py` and `scripts/milestone5_oov_attack.py` already
compute it. What this layer adds is what a classifier evaluation needs that
those two scripts had no occasion to build: confusion matrices, ROC/PR curves,
calibration diagnostics stated honestly, attack-budget success tables, and a
paired bootstrap over classification statistics.

```
scripts/evaluate_model.py
    |
    +-- reuses meter.score() on every sample            (indicpass.password.meter)
    +-- reuses ReferenceAttack.build(...).rank(...)      (indicpass.password.reference_attack, Milestone 4)
    +-- reuses CharacterAttack.build(...).rank(...)       (indicpass.password.character_attack, Milestone 5)
    +-- reuses Taxonomy.classify(...)                     (indicpass.password.oov)
    +-- reuses ValidationRow / calibration(...)           (indicpass.password.validation)
    |
    v
indicpass.evaluation.metrics      confusion matrix, accuracy/precision/recall/F1/
                                   macro-F1/balanced accuracy/MCC, ROC-AUC, PR-AUC,
                                   Brier score, ECE, threshold sweep
indicpass.evaluation.budgets      crackable-within-budget, attack-budget tables,
                                   guess-number / rank distribution statistics
indicpass.evaluation.bootstrap    paired percentile bootstrap for the statistics above
indicpass.evaluation.figures      ROC/PR curves, confusion-matrix grid, guess
                                   histograms (reuses indicpass.figures for bars/intervals)
    |
    v
results/evaluation/
    metrics.json, metrics.csv, predictions.jsonl,
    category_metrics.csv, attack_budget.csv,
    evaluation_report.md, figures/*.svg
```

## Why an evaluation layer, and why it looks like this

The brief this was built against asks for accuracy, precision, recall, F1,
ROC-AUC, PR-AUC, a confusion matrix, calibration, attack-budget success rates
and a baseline comparison — the vocabulary of a binary classifier evaluation.
IndicPass is not shipped as a classifier: it is a guess-number estimator, and
until now nothing in this project produced a `(y_true, y_score)` pair for any
of those metrics to consume. Section 1 of that brief requires auditing what
exists before inventing anything, so that audit is recorded here rather than
assumed away.

**What already existed.** `indicpass.password.validation` and
`indicpass.password.uncertainty` (Milestone 4) already implement rank
correlation, signed/absolute error, RMSE, a decile calibration table, a
slope/intercept regression fit, and a percentile bootstrap with paired
differences — a rigorous evaluation, but built around a *ranking* question
("does the estimator order passwords the way an attacker does?"), not a
*classification* question ("is this password crackable within a stated
budget?"). Nothing computed accuracy, a confusion matrix, ROC-AUC, Brier score
or an attack-budget success rate anywhere in the codebase before this layer.

**What ground truth this evaluation uses.** This project's two bounded
reference attackers (`reference_attack.py`, Milestone 4; `character_attack.py`,
Milestone 5) already compute the one thing no estimator does: the exact rank
at which one fully specified attacker reaches a password. `crackable(B) =
covered AND rank <= B` (section 3 of the brief's suggested definition) turns
that rank into a binary label without inventing anything — see
`indicpass.evaluation.budgets`. Both attackers' *reports*
(`results/reports/reference_attack_hin.json`,
`results/reports/milestone5_oov_attack.json`) publish only aggregates, not the
1,400 per-sample ranks the scripts compute internally, so
`scripts/evaluate_model.py` reruns each attacker's **primary** configuration —
the same settings `config/password.yaml` already ships — to recover them.
Nothing about the attacks changes; the smallest safe adapter here is rerunning
a deterministic, already-frozen computation to read a level of detail its own
report does not publish, not inventing a new attack.

**Why two ground-truth attackers, not one.** M4 (a wordlist crossed with
rules) cannot rank a single one of the 468 out-of-lexicon Indic targets in the
benchmark — that population is exactly what M5 (a character model) exists
to reach. Reporting classification and ranking metrics against M4 alone would
make every OOV-population metric describe an all-negative label set. Both are
reported throughout, exactly as `README.md`'s own status table already
presents them as the project's two independent bounded attackers.

**Why classification metrics use `config/password.yaml`'s own thresholds.**
Section 6 of the brief requires selecting an operating threshold from a
held-out development split, or reporting threshold-independent metrics if
none exists. This benchmark has no development split — the same generated
1,400-sample corpus is used, unsplit, throughout Milestones 2-5. Rather than
either fabricating a split or refusing to report any thresholded metric, this
evaluation uses the attack-budget values themselves (10^3 .. 10^10, the
`BUDGETS` in `indicpass.evaluation.budgets`) as operating points: four of them
(10^3, 10^6, 10^8, 10^10) are `config/password.yaml`'s own
`strength.thresholds`, fixed before and independently of this evaluation for
an unrelated purpose (the 0-4 strength band). Using them here is not tuning a
threshold on the test set — see `docs/evaluation.md`'s reproduction of that
reasoning inline in `scripts/evaluate_model.py`'s `DEFAULT_BUDGET` constant.
Section 6's diagnostic threshold sweep is still produced (`threshold_sweep` in
`metrics.json`), explicitly labelled as not the basis for any selected
operating point.

**Why Brier score and ECE are not computed on password data.** Neither
IndicPass, the PCFG nor zxcvbn outputs a calibrated probability — a guess
number is not one, and treating `1 / guess_number` (or any other
normalisation) as one would be exactly the fabrication the brief prohibits.
`indicpass.evaluation.metrics.brier_score` and `.expected_calibration_error`
exist and are unit-tested against synthetic probabilities, and both raise
`ValueError` on input outside `[0, 1]` specifically so a caller cannot pass a
guess-based score to them by mistake. What this evaluation reports instead,
reused unchanged, is `indicpass.password.validation.calibration`'s regression
fit (slope/intercept/R² of observed rank on predicted guesses) — a legitimate
calibration analysis for a non-probabilistic score, already computed by the
frozen library.

## The evaluation contract

Every record in `results/evaluation/predictions.jsonl` is one
`(password_id, model)` pair:

```json
{
  "password_id": "indic_word-0007",
  "category": "indic_word",
  "partition": "indic_in_lexicon",
  "in_lexicon": true,
  "construction": "indic/lower",
  "length": 6,
  "model": "indicpass",
  "continuous_score": -4.3253,
  "log10_guesses": 4.3253,
  "guess_number": 21152.0,
  "ground_truth": 1,
  "predicted_label": 1,
  "default_budget": 100000000.0,
  "ground_truth_detail": {
    "m4_reference_attack": {"covered": true, "log10_rank": 3.98},
    "m5_character_attack": {"reachable": true, "log10_rank": 4.51}
  }
}
```

`password_id` is the benchmark's `sample_id`, never the password.
`continuous_score = -log10_guesses`, so **larger is more attackable** — the
direction every ranking function in `indicpass.evaluation.metrics` assumes;
see that module's docstring and
`tests/test_evaluation_metrics.py::test_roc_auc_score_direction_matters` for
the test that would fail if a caller got this backwards. `ground_truth` and
`predicted_label` are evaluated at `default_budget` (10^8) against the M4
attacker; `ground_truth_detail` carries both attackers' raw observations so
any other budget can be recomputed without re-running the pipeline.

`category` is the benchmark generator's label (`english`, `indic_word`,
`indic_numeric`, `indic_year`, `indic_symbol`, `mixed`, `random`).
`partition` is `indicpass.password.oov.Taxonomy`'s finer, dictionary-derived
classification (`indic_in_lexicon`, `oov_name`, `oov_spelling_variant`,
`oov_morphological_variant`, `oov_stem_suffix`, `oov_other`,
`random_control`, `english_control`, `mixed_construction`) — both are
deterministic functions of the corpus and the dictionary, never of an
estimator's prediction, per section 9's requirement.

## Outputs (`results/evaluation/`)

| file | contents |
| --- | --- |
| `metrics.json` | Everything: dataset/model provenance, classification and ranking per estimator/attacker/budget, macro-F1, attack-budget tables, guess/rank distributions, the threshold sweep, calibration, category and partition breakdowns, the baseline comparison, the paired bootstrap, limitations. |
| `metrics.csv` | One row per (model, attacker, budget): accuracy/precision/recall/F1/balanced accuracy/MCC/ROC-AUC/PR-AUC. |
| `category_metrics.csv` | One row per (category-or-partition, model, attacker) at the default budget. |
| `attack_budget.csv` | One row per (series, budget): the two observed attackers plus each estimator's predicted-crackable rate. |
| `predictions.jsonl` | The contract above, one line per (sample, estimator). |
| `evaluation_report.md` | The human-readable synthesis. |
| `figures/*.svg` | `roc.svg`, `precision_recall.svg`, `confusion_matrix.svg`, `calibration.svg`, `attack_budget.svg`, `guess_distribution.svg`, `baseline_comparison.svg`, `category_comparison.svg`. |

Nothing under `results/reports/` is read, written or overwritten by this
script; `results/evaluation/` is a separate directory precisely so this layer
cannot collide with an existing milestone's committed report.

## Running it

```bash
python scripts/evaluate_model.py --languages hin
```

One command, deterministic given the seeds already in `config/password.yaml`
(`evaluation.seed`, `reference_attack.seed`, `character_attack.training_seed`).
Costs roughly what `scripts/reference_attack.py` and
`scripts/milestone5_oov_attack.py` cost combined — dictionary load and PCFG
refit (~20-30s, once), then scoring and ranking 1,400 samples (seconds), then
the paired bootstrap (`--resamples`, default 1000; dominates the runtime).
`--samples N` shrinks the per-category corpus for a fast smoke run;
`--no-report` prints the console summary and writes nothing.

The script rebuilds both attacks a second time, in-process, from scratch, and
compares every rank byte-for-byte against the first build
(`report["reproducibility"]`) — the same self-check
`scripts/reference_attack.py` and `scripts/milestone5_oov_attack.py` already
perform for their own primary arm.

## Tests

```bash
python -m pytest tests/test_evaluation_metrics.py tests/test_evaluation_budgets.py \
    tests/test_evaluation_bootstrap.py tests/test_evaluation_figures.py \
    tests/test_evaluate_model.py
```

These are ordinary, fast members of the default `python -m pytest` run — 51
tests, none of them touching the real 298k-entry dictionary. The pure-math
tests (`test_evaluation_metrics.py`, `test_evaluation_budgets.py`,
`test_evaluation_bootstrap.py`, `test_evaluation_figures.py`) check the
metrics against known-correct values (two of the ROC/PR examples are the
canonical cases from scikit-learn's own docstrings, used here only as
independently-known answers, not as a dependency), zero-division handling,
score direction, and determinism. `test_evaluate_model.py` is the integration
test section 16 requires: it runs the *real* `IndicPassMeter`,
`ReferenceAttack` and `CharacterAttack` — against the same tiny fixture
dictionary `tests/test_reference_attack.py` and `tests/test_character_attack.py`
already use, for the reason those files use it — and asserts the evaluation's
predictions are byte-identical to an independent direct call to
`meter.score()` / `attack.rank()` for the same password.

## Limitations

Stated in full in `evaluation_report.md` and `metrics.json["limitations"]`
every time the script runs; summarised here:

1. Ground truth is the rank of one of two *bounded, fully specified*
   attackers — not a real-world cracking result, and neither attack uses a
   leaked-password corpus.
2. The benchmark has no held-out development split, so no classification
   threshold in this report was tuned on it; the reported operating points
   are `config/password.yaml`'s own pre-existing strength thresholds, and the
   full threshold sweep is diagnostic only.
3. Brier score and ECE are not computed on password data — no estimator here
   outputs a calibrated probability.
4. M4's coverage of the out-of-lexicon population is 0%; M4-conditioned
   metrics on that population describe an all-negative ground truth, which is
   exactly why M5 is reported alongside it throughout.
5. The benchmark is synthetic — a generated corpus from a hand-written word
   bank, not observed passwords. No claim about real Indian passwords'
   distribution is supported by anything in this report.
