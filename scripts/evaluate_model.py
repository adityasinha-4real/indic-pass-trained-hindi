#!/usr/bin/env python
"""Rigorous evaluation layer over the frozen IndicPass password engine.

    python scripts/evaluate_model.py --languages hin

Computes accuracy, precision, recall, F1, macro-F1, balanced accuracy, MCC,
confusion matrices, ROC-AUC, PR-AUC, calibration diagnostics, attack-budget
success rates, guess-number distributions, category-wise breakdowns and a
baseline comparison -- all read from the *existing* research artefacts this
project already produces. It adds no scoring logic, trains nothing, and
changes no threshold, model, dataset or prior: see ``docs/evaluation.md`` for
the full audit this script's design was built from.

Ground truth
------------
This project's research code already computes something no estimator does:
the position at which a fully specified, bounded attacker actually reaches a
password. Two independent such attackers exist --
:mod:`indicpass.password.reference_attack` (Milestone 4, a wordlist crossed
with rules) and :mod:`indicpass.password.character_attack` (Milestone 5, a
character model that also reaches spellings the wordlist lacks). This script
reruns both attackers' PRIMARY configuration (the same settings
``config/password.yaml`` already ships, and the same 1,400-sample benchmark
corpus Milestones 2-5 all use) to recover their per-sample ranks, which
``results/reports/reference_attack_hin.json`` and
``results/reports/milestone5_oov_attack.json`` compute internally but publish
only in aggregate. Nothing here is a new attack or a new estimator; it is the
same construction :mod:`scripts.reference_attack` and
:mod:`scripts.milestone5_oov_attack` already perform, read down to row level.

A password is "crackable within budget B" iff an attacker reached it AND did
so at rank <= B (section 3 of the evaluation brief). An attacker that never
reached a password at all is evidence the password was *not* cracked by that
attacker within any budget up to its own enumerated universe -- never treated
as "unknown" or dropped, and never assigned the universe size.

Order of operations, preserved from both source scripts
---------------------------------------------------------
Every password is scored by every estimator once, before either attack object
exists, and those predictions are reused unchanged. See
``scripts/reference_attack.py`` and ``scripts/milestone5_oov_attack.py`` for
the reasoning; it applies unchanged here.

No password is written to any output. Rows are keyed on ``sample_id``.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import subprocess
import time
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.evaluation import bootstrap as ebo
from indicpass.evaluation import budgets as eb
from indicpass.evaluation import figures as ef
from indicpass.evaluation import metrics as em
from indicpass.figures import PALETTE, grouped_bars
from indicpass.figures import Series as BarSeries
from indicpass.password.benchmark import (
    CATEGORIES,
    GENERATOR_VERSION,
    BenchmarkSample,
    describe_corpus,
    generate_corpus,
)
from indicpass.password.character_attack import (
    ATTACK_VERSION as M5_ATTACK_VERSION,
)
from indicpass.password.character_attack import (
    CharacterAttack,
    CharacterAttackSettings,
    CharacterModel,
    dictionary_stem_corpus,
)
from indicpass.password.dictionary import IndicDict
from indicpass.password.meter import IndicPassMeter, describe_dictionaries, describe_pcfg
from indicpass.password.oov import PARTITIONS, OovTargetRow, Taxonomy
from indicpass.password.reference_attack import (
    ATTACK_VERSION as M4_ATTACK_VERSION,
)
from indicpass.password.reference_attack import (
    AttackSettings,
    Lexicon,
    ReferenceAttack,
    dictionary_lexicon_entries,
)
from indicpass.password.result import guesses_from_log10
from indicpass.password.validation import (
    ESTIMATOR_COLUMNS,
    ESTIMATOR_LABELS,
    ValidationRow,
    combined_predictions,
)
from indicpass.password.validation import (
    calibration as row_calibration,
)

SCRIPT = "evaluate_model"

#: The estimators the report focuses its figures and headline tables on.
#: Every table also reports every column :data:`ESTIMATOR_COLUMNS` populates
#: (including the ``min_*`` combinations), but three keeps the figures legible.
PRIMARY_COLUMNS: tuple[str, ...] = ("indicpass", "pcfg", "baseline")

#: Reported once as "the" classification operating point in the top-level
#: prediction record and in the headline tables -- 10^8, "offline attack, slow
#: hash" in ``config/password.yaml``'s own strength bands. It is one of that
#: config's four pre-existing thresholds, fixed before and independently of
#: this evaluation, so using it as a frozen operating point is not a
#: threshold tuned on this test set. See ``docs/evaluation.md`` section 6.
DEFAULT_BUDGET = 1.0e8

#: Threshold grid for the diagnostic sweep in section 6 of the brief. Spans
#: the guess-number range this project's own thresholds and reports live in;
#: it is not fit to this run's data.
SWEEP_LOG10_THRESHOLDS: tuple[float, ...] = tuple(range(0, 18))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="evaluate_model.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--samples", type=int, metavar="N", help="Samples per category.")
    parser.add_argument("--seed", type=int, metavar="N", help="Corpus seed.")
    parser.add_argument("--dictionary", type=Path, metavar="FILE", help="Dictionary to use.")
    parser.add_argument(
        "--output-dir", type=Path, metavar="DIR",
        help="Where results/evaluation/ lands. Defaults to <project root>/results/evaluation.",
    )
    parser.add_argument(
        "--resamples", type=int, default=1000, metavar="N",
        help="Bootstrap resamples for the paired classification intervals (default 1000).",
    )
    parser.add_argument("--no-report", action="store_true", help="Print only; write no files.")
    return parser


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


# -- scoring (identical construction to scripts/reference_attack.py) --------


def score_predictions(
    meter: IndicPassMeter, samples: Sequence[BenchmarkSample]
) -> dict[str, dict[str, float]]:
    predictions: dict[str, dict[str, float]] = {}
    for sample in samples:
        result = meter.score(sample.password)
        predictions[sample.sample_id] = combined_predictions(
            indicpass=result.log10_guesses,
            pcfg=result.pcfg_log10_guesses,
            baseline=result.baseline_log10_guesses,
        )
    return predictions


def build_m4_rows(
    attack: ReferenceAttack,
    samples: Sequence[BenchmarkSample],
    predictions: Mapping[str, Mapping[str, float]],
) -> list[ValidationRow]:
    """Same construction as ``scripts/reference_attack.py::build_rows``."""
    rows: list[ValidationRow] = []
    for sample in samples:
        observed = attack.rank(sample.password)
        rows.append(
            ValidationRow(
                sample_id=sample.sample_id,
                category=sample.category,
                construction=sample.construction,
                length=len(sample.password),
                covered=observed.covered,
                reference_rank=observed.rank,
                log10_reference_rank=observed.log10_rank,
                rule=observed.rule,
                predictions=dict(predictions[sample.sample_id]),
                unseen_stem=not attack.stem_in_lexicon(sample.password),
                case_variant=sample.construction.endswith(("/capitalized", "/upper")),
            )
        )
    return rows


def build_m5_rows(
    attack: CharacterAttack,
    samples: Sequence[BenchmarkSample],
    taxonomy: Taxonomy,
    predictions: Mapping[str, Mapping[str, float]],
) -> list[OovTargetRow]:
    """Same construction as ``scripts/milestone5_oov_attack.py::build_rows``."""
    rows: list[OovTargetRow] = []
    for sample in samples:
        observed = attack.rank(sample.password)
        rows.append(
            OovTargetRow(
                sample_id=sample.sample_id,
                category=sample.category,
                construction=sample.construction,
                length=len(sample.password),
                classification=taxonomy.classify(sample.password, sample.category),
                reachable=observed.reachable,
                rank=observed.rank,
                log10_rank=observed.log10_rank,
                shape=observed.shape,
                level=observed.level,
                reason=observed.reason,
                predictions=dict(predictions[sample.sample_id]),
            )
        )
    return rows


def available_columns(rows: Sequence[ValidationRow]) -> list[str]:
    present = {name for row in rows for name in row.predictions}
    return [name for name in ESTIMATOR_COLUMNS if name in present]


# -- the evaluation contract (section 2) -------------------------------------


@dataclasses.dataclass(frozen=True)
class EvalRecord:
    """One (password, estimator) pair. Never carries the password itself."""

    sample_id: str
    category: str
    partition: str
    in_lexicon: bool
    construction: str
    length: int
    model: str
    log10_guesses: float

    m4_covered: bool
    m4_log10_rank: float | None
    m5_reachable: bool
    m5_log10_rank: float | None

    def crackable(self, attacker: str, budget: float) -> bool:
        if attacker == "m4":
            return eb.crackable_within_budget(self.m4_covered, self._m4_rank(), budget)
        return eb.crackable_within_budget(self.m5_reachable, self._m5_rank(), budget)

    def _m4_rank(self) -> float | None:
        return None if self.m4_log10_rank is None else 10.0**self.m4_log10_rank
    def _m5_rank(self) -> float | None:
        return None if self.m5_log10_rank is None else 10.0**self.m5_log10_rank

    def predicted_crackable(self, budget: float) -> bool:
        return self.log10_guesses <= math.log10(budget)

    def to_dict(self) -> dict[str, Any]:
        default_ground_truth = self.crackable("m4", DEFAULT_BUDGET)
        return {
            "password_id": self.sample_id,
            "category": self.category,
            "partition": self.partition,
            "in_lexicon": self.in_lexicon,
            "construction": self.construction,
            "length": self.length,
            "model": self.model,
            "continuous_score": round(-self.log10_guesses, 6),
            "continuous_score_note": (
                "-log10(guess_number): HIGHER means the estimator considers this "
                "password MORE attackable. See indicpass.evaluation.metrics's module "
                "docstring for the score-direction convention."
            ),
            "log10_guesses": round(self.log10_guesses, 6),
            "guess_number": guesses_from_log10(self.log10_guesses),
            "ground_truth": int(default_ground_truth),
            "ground_truth_definition": (
                f"1 iff Milestone 4's reference attack reached this password at "
                f"rank <= {DEFAULT_BUDGET:g}."
            ),
            "predicted_label": int(self.predicted_crackable(DEFAULT_BUDGET)),
            "default_budget": DEFAULT_BUDGET,
            "ground_truth_detail": {
                "m4_reference_attack": {
                    "covered": self.m4_covered,
                    "log10_rank": self.m4_log10_rank,
                },
                "m5_character_attack": {
                    "reachable": self.m5_reachable,
                    "log10_rank": self.m5_log10_rank,
                },
            },
        }


def build_records(
    samples: Sequence[BenchmarkSample],
    m4_rows: Mapping[str, ValidationRow],
    m5_rows: Mapping[str, OovTargetRow],
    columns: Sequence[str],
) -> list[EvalRecord]:
    records: list[EvalRecord] = []
    for sample in samples:
        m4 = m4_rows[sample.sample_id]
        m5 = m5_rows[sample.sample_id]
        for column in columns:
            if column not in m4.predictions:
                continue
            records.append(
                EvalRecord(
                    sample_id=sample.sample_id,
                    category=sample.category,
                    partition=m5.partition,
                    in_lexicon=m5.in_lexicon,
                    construction=sample.construction,
                    length=len(sample.password),
                    model=column,
                    log10_guesses=m4.predictions[column],
                    m4_covered=m4.covered,
                    m4_log10_rank=m4.log10_reference_rank,
                    m5_reachable=m5.reachable,
                    m5_log10_rank=m5.log10_rank,
                )
            )
    return records


# -- classification + ranking, per estimator / attacker / budget ------------


def _y_true(records: Sequence[EvalRecord], attacker: str, budget: float) -> list[int]:
    return [int(record.crackable(attacker, budget)) for record in records]


def _y_score(records: Sequence[EvalRecord]) -> list[float]:
    """Higher = more attackable, per :mod:`indicpass.evaluation.metrics`'s convention."""
    return [-record.log10_guesses for record in records]


def classification_and_ranking(
    records_by_model: Mapping[str, list[EvalRecord]],
    *,
    attackers: Sequence[str] = ("m4", "m5"),
    budgets: Sequence[float] = eb.BUDGETS,
) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for model, records in records_by_model.items():
        score = _y_score(records)
        out[model] = {}
        for attacker in attackers:
            out[model][attacker] = []
            for budget in budgets:
                truth = _y_true(records, attacker, budget)
                predicted = [1 if s >= -math.log10(budget) else 0 for s in score]
                confusion = em.confusion_matrix(truth, predicted)
                out[model][attacker].append(
                    {
                        "budget": budget,
                        "samples": len(records),
                        "confusion_matrix": confusion.to_dict(),
                        "accuracy": em.accuracy(confusion),
                        "precision": em.precision(confusion),
                        "recall": em.recall(confusion),
                        "f1": em.f1(confusion),
                        "balanced_accuracy": em.balanced_accuracy(confusion),
                        "mcc": em.mcc(confusion),
                        "roc_auc": em.roc_auc(truth, score),
                        "pr_auc": em.pr_auc(truth, score),
                        "positive_rate_ground_truth": (
                            sum(truth) / len(truth) if truth else None
                        ),
                        "positive_rate_predicted": (
                            sum(predicted) / len(predicted) if predicted else None
                        ),
                    }
                )
    return out


def macro_f1_at(
    records_by_model: Mapping[str, list[EvalRecord]], attacker: str, budget: float
) -> dict[str, Any]:
    """Macro-F1, computed generically over the {0,1} label set -- section 4."""
    out: dict[str, Any] = {}
    for model, records in records_by_model.items():
        truth = _y_true(records, attacker, budget)
        score = _y_score(records)
        predicted = [1 if s >= -math.log10(budget) else 0 for s in score]
        out[model] = em.macro_f1(truth, predicted, labels=[0, 1])
    return out


# -- report assembly ----------------------------------------------------------


def _fmt(value: Any, spec: str = ".3f") -> str:
    if value is None:
        return "--"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "inf"
    return format(value, spec) if isinstance(value, (int, float)) else str(value)


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append

    add(f"# Rigorous evaluation -- {report['language']}")
    add("")
    add(f"Generated {report['generated_at']} from {report['project']} at "
        f"`{report['git_commit'][:12]}`.")
    add("")
    add("This report adds classification, ranking and calibration metrics on top of "
        "the frozen research code's own two bounded reference attackers. It computes "
        "no guess number, match, PCFG probability or attack rank of its own -- see "
        "`docs/evaluation.md`.")
    add("")

    add("## 1. Dataset")
    add("")
    corpus = report["dataset"]
    add(f"{corpus['total_samples']} generated samples (seed {report['corpus_seed']}), the "
        f"SAME corpus Milestones 2-5 use. Not a held-out split: the project has no "
        f"train/dev/test partition of this benchmark, which is why section 6 below "
        f"reports a diagnostic threshold sweep rather than a selected operating "
        f"threshold. Categories:")
    add("")
    add("| category | samples |")
    add("| --- | ---: |")
    for name, info in corpus["categories"].items():
        add(f"| {name} | {info['samples']} |")
    add("")

    add("## 2. Ground truth")
    add("")
    add("Two independent bounded attackers, both already part of this project:")
    add("")
    add(f"* **M4** reference attack (wordlist x rules), version `{M4_ATTACK_VERSION}`. "
        f"Coverage: {report['coverage']['m4']['coverage']:.1%} "
        f"({report['coverage']['m4']['covered']}/{report['coverage']['m4']['targets']}).")
    add(f"* **M5** character attack (reaches out-of-lexicon spellings), version "
        f"`{M5_ATTACK_VERSION}`. Coverage: {report['coverage']['m5']['coverage']:.1%} "
        f"({report['coverage']['m5']['covered']}/{report['coverage']['m5']['targets']}).")
    add("")
    add("`crackable(B) = covered AND rank <= B`. An attacker that never reached a "
        "password contributes 0 to every budget's success count -- never the "
        "universe size, never dropped.")
    add("")

    add("## 3. Classification, ranking, at the default budget")
    add("")
    add(f"Default reporting budget: 10^{math.log10(report['default_budget']):.0f} "
        "candidates -- one of `config/password.yaml`'s own four pre-existing "
        "strength thresholds, fixed independently of this evaluation.")
    add("")
    for attacker_key, attacker_label in (("m4", "M4 (wordlist)"), ("m5", "M5 (character model)")):
        add(f"**Ground truth: {attacker_label}**")
        add("")
        add("| estimator | n | accuracy | precision | recall | F1 | balanced acc | MCC | "
            "ROC-AUC | PR-AUC |")
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
        for model in PRIMARY_COLUMNS:
            rows = report["classification"].get(model, {}).get(attacker_key, [])
            row = next((r for r in rows if r["budget"] == report["default_budget"]), None)
            if row is None:
                continue
            label = ESTIMATOR_LABELS.get(model, model)
            add(f"| {label} | {row['samples']} | {_fmt(row['accuracy'], '.3f')} | "
                f"{_fmt(row['precision'], '.3f')} | {_fmt(row['recall'], '.3f')} | "
                f"{_fmt(row['f1'], '.3f')} | {_fmt(row['balanced_accuracy'], '.3f')} | "
                f"{_fmt(row['mcc'], '.3f')} | {_fmt(row['roc_auc'], '.3f')} | "
                f"{_fmt(row['pr_auc'], '.3f')} |")
        add("")

    add("## 4. Attack-budget success rates")
    add("")
    add("Observed (ground truth) success rate -- the fraction of ALL targets an "
        "attacker actually cracked within each budget:")
    add("")
    add("| budget | M4 success | M5 success |")
    add("| ---: | ---: | ---: |")
    m4_budget = {row["budget"]: row for row in report["attack_budget"]["m4"]}
    m5_budget = {row["budget"]: row for row in report["attack_budget"]["m5"]}
    for budget in eb.BUDGETS:
        add(f"| 10^{math.log10(budget):.0f} | "
            f"{_fmt(m4_budget[budget]['success_rate'], '.1%')} | "
            f"{_fmt(m5_budget[budget]['success_rate'], '.1%')} |")
    add("")

    add("## 5. Guess-number / rank distributions")
    add("")
    add("`estimated` = a model's own guess number. `observed` = an attack's rank, "
        "among the targets it reached. Never averaged together.")
    add("")
    add("| series | n | median log10 | geometric-mean log10 | P10 | P90 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name, stats in report["distributions"].items():
        q = stats["quantiles_log10"]
        add(f"| {name} | {stats['samples']} | {_fmt(stats['median_log10'], '.2f')} | "
            f"{_fmt(stats['geometric_mean_log10'], '.2f')} | "
            f"{_fmt(q.get('p10'), '.2f')} | {_fmt(q.get('p90'), '.2f')} |")
    add("")

    add("## 6. Threshold sweep (diagnostic; no threshold is selected)")
    add("")
    add("No held-out development split exists for this frozen benchmark, so per the "
        "evaluation protocol, no single threshold below is selected as a recommended "
        "operating point -- section 3's budget-anchored classification above is the "
        "only frozen, non-tuned operating point this report uses. This table is "
        "provided for diagnostic and ROC-construction purposes only, for IndicPass "
        "against M4 at the default budget.")
    add("")
    add("| log10 threshold | precision | recall | F1 | accuracy | balanced acc | MCC |")
    add("| ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in report["threshold_sweep"]:
        add(f"| {row['threshold']:.0f} | {_fmt(row['precision'], '.3f')} | "
            f"{_fmt(row['recall'], '.3f')} | {_fmt(row['f1'], '.3f')} | "
            f"{_fmt(row['accuracy'], '.3f')} | {_fmt(row['balanced_accuracy'], '.3f')} | "
            f"{_fmt(row['mcc'], '.3f')} |")
    add("")

    add("## 7. Calibration")
    add("")
    add("This project's guess numbers are not probabilities, so Brier score and "
        "Expected Calibration Error are not computed on them -- doing so would "
        "require treating a guess count as a probability, which "
        "`indicpass.evaluation.metrics` refuses to do (its `brier_score` and "
        "`expected_calibration_error` raise on input outside [0, 1]). Both functions "
        "exist and are unit-tested against synthetic probabilities.")
    add("")
    add("What IS available and reused unchanged from "
        "`indicpass.password.validation.calibration`: an ordinary-least-squares "
        "regression of observed log10 rank on predicted log10 guesses. Slope 1 / "
        "intercept 0 is perfect calibration against that attack.")
    add("")
    add("| estimator | attacker | n | slope | intercept | r^2 |")
    add("| --- | --- | ---: | ---: | ---: | ---: |")
    for entry in report["calibration"]:
        add(f"| {entry['label']} | {entry['attacker']} | {entry['samples']} | "
            f"{_fmt(entry['slope'])} | {_fmt(entry['intercept'])} | {_fmt(entry['r_squared'])} |")
    add("")

    add("## 8. Category-wise")
    add("")
    add("At the default budget, ground truth M4, IndicPass only (`category_metrics.csv` "
        "carries every estimator and both attackers):")
    add("")
    add("| category | n | accuracy | F1 | ROC-AUC | M4 coverage |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in report["category_metrics"]:
        if (
            row["model"] != "indicpass"
            or row["attacker"] != "m4"
            or row["group_kind"] != "category"
        ):
            continue
        add(f"| {row['group']} | {row['samples']} | {_fmt(row['accuracy'], '.3f')} | "
            f"{_fmt(row['f1'], '.3f')} | {_fmt(row['roc_auc'], '.3f')} | "
            f"{_fmt(row['coverage'], '.1%')} |")
    add("")
    add("By OOV partition (deterministic dictionary-membership classification, not "
        "model-derived -- see `indicpass.password.oov.Taxonomy`):")
    add("")
    add("| partition | n | accuracy | F1 | ROC-AUC | M4 coverage |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in report["category_metrics"]:
        if (
            row["model"] != "indicpass"
            or row["attacker"] != "m4"
            or row["group_kind"] != "partition"
        ):
            continue
        add(f"| {row['group']} | {row['samples']} | {_fmt(row['accuracy'], '.3f')} | "
            f"{_fmt(row['f1'], '.3f')} | {_fmt(row['roc_auc'], '.3f')} | "
            f"{_fmt(row['coverage'], '.1%')} |")
    add("")

    add("## 9. Baseline comparison")
    add("")
    add("Same records, same attacker (M4), same default budget:")
    add("")
    add("| metric | IndicPass | PCFG | zxcvbn | IndicPass - zxcvbn | PCFG - zxcvbn |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for metric in ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"):
        values = report["baseline_comparison"][metric]
        add(f"| {metric} | {_fmt(values['indicpass'])} | {_fmt(values['pcfg'])} | "
            f"{_fmt(values['baseline'])} | {_fmt(values['indicpass_minus_baseline'], '+.3f')} | "
            f"{_fmt(values['pcfg_minus_baseline'], '+.3f')} |")
    add("")

    add("## 10. Paired bootstrap (classification statistics)")
    add("")
    add(f"{report['bootstrap']['m4']['resamples']} resamples, percentile method, "
        f"{report['bootstrap']['m4']['confidence']:.0%} interval, ground truth M4, "
        f"default budget. An interval excluding zero is reported as excluding zero; "
        "it is not a significance test.")
    add("")
    add("| difference | statistic | value | CI low | CI high | excludes 0 |")
    add("| --- | --- | ---: | ---: | ---: | --- |")
    for pair_name, pair in report["bootstrap"]["m4"]["differences"].items():
        for statistic in ("accuracy", "f1", "mcc", "roc_auc"):
            entry = pair[statistic]
            add(f"| {pair_name} | {statistic} | {_fmt(entry['point'])} | "
                f"{_fmt(entry['ci_low'])} | {_fmt(entry['ci_high'])} | "
                f"{entry['excludes_zero']} |")
    add("")

    add("## 11. Limitations")
    add("")
    for item in report["limitations"]:
        add(f"* {item}")
    add("")
    add("---")
    add("")
    add(f"Reproducibility self-check: M4 ranks identical across two independent "
        f"builds: {report['reproducibility']['m4_ranks_match']}. M5 ranks identical: "
        f"{report['reproducibility']['m5_ranks_match']}.")
    add("")
    return "\n".join(lines) + "\n"


LIMITATIONS: tuple[str, ...] = (
    "Ground truth is the rank at which ONE of two bounded, fully specified attackers "
    "reaches a password -- not a real-world cracking result. Neither attacker uses a "
    "leaked-password corpus; see docs/password_strength_design.md sections 15-16.",
    "The corpus is the SAME generated 1,400-sample benchmark Milestones 2-5 use. It "
    "has no held-out development split, so section 6's threshold sweep is diagnostic "
    "only; section 3's budget-anchored classification uses config/password.yaml's "
    "pre-existing strength thresholds as its only frozen operating points.",
    "Brier score and Expected Calibration Error are not computed: none of the three "
    "estimators outputs a calibrated probability, and indicpass.evaluation.metrics "
    "refuses to treat a guess number as one. Regression calibration (slope/intercept "
    "against observed rank) is reported instead, reusing "
    "indicpass.password.validation.calibration unchanged.",
    "M4's coverage is conditional: it can rank 0 of 468 out-of-lexicon Indic targets "
    "(its universe is a wordlist), so M4-conditioned metrics on that population "
    "reflect an all-negative ground truth. M5 exists precisely to cover that "
    "population and is reported alongside M4 throughout for exactly this reason.",
    "Category and partition labels come from the benchmark generator and from "
    "indicpass.password.oov.Taxonomy's dictionary-membership rules -- never from an "
    "estimator's own prediction.",
    "This is a synthetic benchmark from a hand-written word bank, not observed "
    "passwords. No claim about the distribution of real Indian passwords is "
    "supported by anything in this report.",
)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("This evaluation is built from one dictionary. Pass --languages hin.")
        return 2
    language = languages[0]

    dictionary_config = config.password_section("dictionary")
    tier_order = [str(tier["name"]) for tier in (dictionary_config.get("tiers") or [])]
    evaluation = config.password_section("evaluation")
    seed = args.seed if args.seed is not None else int(evaluation.get("seed", 42))
    per_category = args.samples or int(
        (evaluation.get("benchmark") or {}).get("samples_per_category", 200)
    )

    path = config.resolve(
        args.dictionary or (dictionary_config.get("files") or {})[language.code]
    )
    logger.info("Loading %s", config.relative(path))
    dictionary = IndicDict.load(path, language=language.code, tier_order=tier_order)
    logger.info("  %d entries, %d ranked", len(dictionary), dictionary.ranked_total)

    meter = IndicPassMeter.from_config(
        config, languages=[language.code], dictionary_paths=[path]
    )
    if meter.baseline is None:
        logger.error("No baseline loaded. This evaluation requires zxcvbn to run.")
        return 2
    if meter.pcfg is None:
        logger.error(
            "No PCFG loaded. Train one with scripts/train_pcfg.py --languages hin."
        )
        return 2

    samples = generate_corpus(seed=seed, samples_per_category=per_category)
    logger.info("Corpus: %d samples across %d categories", len(samples), len(CATEGORIES))

    started = time.perf_counter()
    predictions = score_predictions(meter, samples)
    logger.info(
        "Scored %d samples with three estimators in %.1fs",
        len(predictions), time.perf_counter() - started,
    )

    # -- M4: the reference (wordlist) attack ---------------------------------
    m4_section = config.password_section("reference_attack")
    m4_settings = AttackSettings.from_config(m4_section)
    lexicon_entries = dictionary_lexicon_entries(dictionary)
    lexicon = Lexicon.build(
        lexicon_entries, order=m4_settings.lexicon_order,
        seed=m4_settings.seed, size=m4_settings.lexicon_size,
    )
    m4_attack = ReferenceAttack.build(lexicon, m4_settings)
    started = time.perf_counter()
    m4_rows_list = build_m4_rows(m4_attack, samples, predictions)
    m4_rows = {row.sample_id: row for row in m4_rows_list}
    logger.info(
        "M4 (reference attack): %d/%d covered in %.1fs",
        sum(1 for r in m4_rows_list if r.covered), len(m4_rows_list),
        time.perf_counter() - started,
    )

    # -- M5: the character-model (out-of-lexicon) attack ---------------------
    m5_section = config.password_section("character_attack")
    m5_settings = CharacterAttackSettings.from_config(m5_section)
    stem_words = dictionary_stem_corpus(dictionary)
    taxonomy = Taxonomy(stem_words)
    character_model = CharacterModel.train(
        stem_words, order=m5_settings.order, smoothing=m5_settings.smoothing,
        precision=m5_settings.precision, kind=m5_settings.model,
        share=m5_settings.training_share, seed=m5_settings.training_seed,
    )
    m5_attack = CharacterAttack.build(character_model, m5_settings)
    started = time.perf_counter()
    m5_rows_list = build_m5_rows(m5_attack, samples, taxonomy, predictions)
    m5_rows = {row.sample_id: row for row in m5_rows_list}
    logger.info(
        "M5 (character attack): %d/%d reachable in %.1fs",
        sum(1 for r in m5_rows_list if r.reachable), len(m5_rows_list),
        time.perf_counter() - started,
    )

    # -- reproducibility self-check: rebuild both attacks from scratch -------
    again_lexicon = Lexicon.build(
        lexicon_entries, order=m4_settings.lexicon_order,
        seed=m4_settings.seed, size=m4_settings.lexicon_size,
    )
    again_m4 = ReferenceAttack.build(again_lexicon, m4_settings)
    again_m4_rows = build_m4_rows(again_m4, samples, predictions)
    m4_ranks_match = [r.reference_rank for r in again_m4_rows] == [
        r.reference_rank for r in m4_rows_list
    ]

    again_model = CharacterModel.train(
        stem_words, order=m5_settings.order, smoothing=m5_settings.smoothing,
        precision=m5_settings.precision, kind=m5_settings.model,
        share=m5_settings.training_share, seed=m5_settings.training_seed,
    )
    again_m5 = CharacterAttack.build(again_model, m5_settings)
    again_m5_rows = build_m5_rows(again_m5, samples, taxonomy, predictions)
    m5_ranks_match = [r.rank for r in again_m5_rows] == [r.rank for r in m5_rows_list]
    logger.info(
        "Reproducibility self-check: M4 ranks match=%s, M5 ranks match=%s",
        m4_ranks_match, m5_ranks_match,
    )

    # -- assemble the evaluation contract -------------------------------------
    columns = available_columns(m4_rows_list)
    records = build_records(samples, m4_rows, m5_rows, columns)
    records_by_model: dict[str, list[EvalRecord]] = {
        column: [r for r in records if r.model == column] for column in columns
    }

    classification = classification_and_ranking(records_by_model)
    default_macro_f1 = {
        "m4": macro_f1_at(records_by_model, "m4", DEFAULT_BUDGET),
        "m5": macro_f1_at(records_by_model, "m5", DEFAULT_BUDGET),
    }

    coverage = {
        "m4": {
            "targets": len(m4_rows_list),
            "covered": sum(1 for r in m4_rows_list if r.covered),
            "coverage": sum(1 for r in m4_rows_list if r.covered) / len(m4_rows_list),
        },
        "m5": {
            "targets": len(m5_rows_list),
            "covered": sum(1 for r in m5_rows_list if r.reachable),
            "coverage": sum(1 for r in m5_rows_list if r.reachable) / len(m5_rows_list),
        },
    }

    attack_budget = {
        "m4": eb.attack_budget_table(
            [r.covered for r in m4_rows_list], [r.reference_rank for r in m4_rows_list]
        ),
        "m5": eb.attack_budget_table(
            [r.reachable for r in m5_rows_list], [r.rank for r in m5_rows_list]
        ),
    }
    for column in PRIMARY_COLUMNS:
        recs = records_by_model.get(column, [])
        attack_budget[f"predicted_{column}"] = [
            {
                "budget": budget,
                "count": sum(1 for r in recs if r.predicted_crackable(budget)),
                "total": len(recs),
                "success_rate": (
                    sum(1 for r in recs if r.predicted_crackable(budget)) / len(recs)
                    if recs else None
                ),
            }
            for budget in eb.BUDGETS
        ]

    distributions = {
        f"estimated_{column}": eb.guess_number_stats(
            [r.log10_guesses for r in records_by_model.get(column, [])], source="estimated"
        ).to_dict()
        for column in PRIMARY_COLUMNS
    }
    distributions["observed_m4"] = eb.guess_number_stats(
        [
            r.log10_reference_rank
            for r in m4_rows_list
            if r.covered and r.log10_reference_rank is not None
        ],
        source="observed",
    ).to_dict()
    distributions["observed_m5"] = eb.guess_number_stats(
        [r.log10_rank for r in m5_rows_list if r.reachable and r.log10_rank is not None],
        source="observed",
    ).to_dict()

    indicpass_scores = _y_score(records_by_model.get("indicpass", []))
    indicpass_truth_m4 = _y_true(records_by_model.get("indicpass", []), "m4", DEFAULT_BUDGET)
    threshold_sweep = [
        row.to_dict()
        for row in em.threshold_sweep(
            indicpass_truth_m4, indicpass_scores,
            [-t for t in SWEEP_LOG10_THRESHOLDS],
        )
    ]
    for row, log10_threshold in zip(threshold_sweep, SWEEP_LOG10_THRESHOLDS, strict=True):
        row["threshold"] = log10_threshold

    calibration_rows: list[dict[str, Any]] = []
    m5_validation_rows = [row.as_validation_row() for row in m5_rows_list]
    for column in columns:
        for attacker_key, attacker_rows in (("m4", m4_rows_list), ("m5", m5_validation_rows)):
            entry = row_calibration(attacker_rows, column)
            calibration_rows.append(
                {
                    "estimator": column,
                    "label": ESTIMATOR_LABELS.get(column, column),
                    "attacker": attacker_key,
                    "samples": entry.samples,
                    "slope": entry.slope,
                    "intercept": entry.intercept,
                    "r_squared": entry.r_squared,
                }
            )

    category_metrics: list[dict[str, Any]] = []
    for group_kind, groups, group_of in (
        ("category", CATEGORIES, lambda r: r.category),
        ("partition", PARTITIONS, lambda r: r.partition),
    ):
        for group in groups:
            for column in PRIMARY_COLUMNS:
                recs = [r for r in records_by_model.get(column, []) if group_of(r) == group]
                if not recs:
                    continue
                for attacker_key in ("m4", "m5"):
                    truth = _y_true(recs, attacker_key, DEFAULT_BUDGET)
                    score = _y_score(recs)
                    predicted = [1 if s >= -math.log10(DEFAULT_BUDGET) else 0 for s in score]
                    confusion = em.confusion_matrix(truth, predicted)
                    covered_flags = (
                        [r.m4_covered for r in recs] if attacker_key == "m4"
                        else [r.m5_reachable for r in recs]
                    )
                    category_metrics.append(
                        {
                            "group_kind": group_kind,
                            "group": group,
                            "model": column,
                            "attacker": attacker_key,
                            "samples": len(recs),
                            "coverage": sum(covered_flags) / len(covered_flags),
                            "accuracy": em.accuracy(confusion),
                            "precision": em.precision(confusion),
                            "recall": em.recall(confusion),
                            "f1": em.f1(confusion),
                            "mcc": em.mcc(confusion),
                            "roc_auc": em.roc_auc(truth, score),
                        }
                    )

    def _at_default(model: str, attacker: str) -> dict[str, Any]:
        rows = classification.get(model, {}).get(attacker, [])
        return next((r for r in rows if r["budget"] == DEFAULT_BUDGET), {})

    baseline_comparison: dict[str, Any] = {}
    for metric in ("accuracy", "precision", "recall", "f1", "roc_auc", "pr_auc"):
        indic_v = _at_default("indicpass", "m4").get(metric)
        pcfg_v = _at_default("pcfg", "m4").get(metric)
        base_v = _at_default("baseline", "m4").get(metric)
        baseline_comparison[metric] = {
            "indicpass": indic_v,
            "pcfg": pcfg_v,
            "baseline": base_v,
            "indicpass_minus_baseline": (
                None if indic_v is None or base_v is None else round(indic_v - base_v, 4)
            ),
            "pcfg_minus_baseline": (
                None if pcfg_v is None or base_v is None else round(pcfg_v - base_v, 4)
            ),
        }

    bootstrap_scores = {name: _y_score(records_by_model[name]) for name in PRIMARY_COLUMNS}
    bootstrap = {
        attacker_key: ebo.bootstrap_classification(
            _y_true(records_by_model["indicpass"], attacker_key, DEFAULT_BUDGET),
            bootstrap_scores,
            threshold=-math.log10(DEFAULT_BUDGET),
            pairs=[("indicpass", "baseline"), ("pcfg", "baseline"), ("pcfg", "indicpass")],
            seed=seed,
            resamples=args.resamples,
            label=f"evaluate_model:{attacker_key}",
        )
        for attacker_key in ("m4", "m5")
    }

    header = {
        "report": "evaluate_model",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(config.root),
        "project": f"{config.name} v{config.version}",
        "language": language.code,
        "corpus_seed": seed,
        "default_budget": DEFAULT_BUDGET,
        "budgets": list(eb.BUDGETS),
        "dataset": {**describe_corpus(samples), "generator_version": GENERATOR_VERSION},
        "dictionaries": describe_dictionaries(meter),
        "pcfg": describe_pcfg(meter),
        "baseline_name": meter.baseline.name,
        "estimator_columns": {name: ESTIMATOR_LABELS[name] for name in columns},
        "attack_versions": {
            "m4_reference_attack": M4_ATTACK_VERSION,
            "m5_character_attack": M5_ATTACK_VERSION,
        },
    }

    report: dict[str, Any] = {
        **header,
        "coverage": coverage,
        "classification": classification,
        "macro_f1_at_default_budget": default_macro_f1,
        "attack_budget": attack_budget,
        "distributions": distributions,
        "threshold_sweep": threshold_sweep,
        "calibration": calibration_rows,
        "category_metrics": category_metrics,
        "baseline_comparison": baseline_comparison,
        "bootstrap": bootstrap,
        "reproducibility": {
            "m4_ranks_match": m4_ranks_match,
            "m5_ranks_match": m5_ranks_match,
            "note": (
                "Both attacks were rebuilt from scratch, in-process, and re-ranked "
                "every sample a second time; the ranks above compare the two builds."
            ),
        },
        "limitations": list(LIMITATIONS),
    }

    print_console(report)
    if args.no_report:
        return 0

    default_output = config.resolve("results/evaluation")
    output_dir = config.resolve(args.output_dir) if args.output_dir else default_output
    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    (output_dir / "metrics.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    write_metrics_csv(output_dir / "metrics.csv", classification)
    write_category_csv(output_dir / "category_metrics.csv", category_metrics)
    write_budget_csv(output_dir / "attack_budget.csv", attack_budget)
    write_predictions_jsonl(output_dir / "predictions.jsonl", records)
    write_figures(figures_dir, report, records_by_model, m4_rows_list)

    (output_dir / "evaluation_report.md").write_text(render(report), encoding="utf-8")
    logger.info("Evaluation written to %s", config.relative(output_dir))
    return 0


def print_console(report: dict[str, Any]) -> None:
    width = 92
    print(f"\n{'=' * width}")
    print("RIGOROUS EVALUATION -- classification, ranking, calibration, attack budgets")
    print(f"{'=' * width}")
    print(f"  coverage       M4 {report['coverage']['m4']['coverage']:.1%}   "
          f"M5 {report['coverage']['m5']['coverage']:.1%}")
    print(f"  default budget 10^{math.log10(report['default_budget']):.0f}")
    print()
    print(
        f"  {'estimator':<16}{'attacker':<6}{'acc':>7}{'F1':>7}{'MCC':>7}"
        f"{'ROC-AUC':>9}{'PR-AUC':>9}"
    )
    for model in PRIMARY_COLUMNS:
        for attacker in ("m4", "m5"):
            rows = report["classification"].get(model, {}).get(attacker, [])
            row = next((r for r in rows if r["budget"] == report["default_budget"]), None)
            if row is None:
                continue
            print(f"  {model:<16}{attacker:<6}{_fmt(row['accuracy']):>7}{_fmt(row['f1']):>7}"
                  f"{_fmt(row['mcc']):>7}{_fmt(row['roc_auc']):>9}{_fmt(row['pr_auc']):>9}")
    print()
    print(f"  reproducibility: M4 ranks match {report['reproducibility']['m4_ranks_match']}, "
          f"M5 ranks match {report['reproducibility']['m5_ranks_match']}")
    print()


# -- CSV / JSONL writers ------------------------------------------------------


def write_metrics_csv(path: Path, classification: Mapping[str, Any]) -> None:
    lines = [
        "model,attacker,budget,samples,accuracy,precision,recall,f1,balanced_accuracy,mcc,roc_auc,pr_auc"
    ]
    for model, by_attacker in classification.items():
        for attacker, rows in by_attacker.items():
            for row in rows:
                lines.append(
                    ",".join(
                        str(x) for x in (
                            model, attacker, row["budget"], row["samples"],
                            row["accuracy"], row["precision"], row["recall"], row["f1"],
                            row["balanced_accuracy"], row["mcc"], row["roc_auc"], row["pr_auc"],
                        )
                    )
                )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_category_csv(path: Path, category_metrics: Sequence[Mapping[str, Any]]) -> None:
    lines = [
        "group_kind,group,model,attacker,samples,coverage,accuracy,precision,recall,f1,mcc,roc_auc"
    ]
    for row in category_metrics:
        lines.append(
            ",".join(
                str(row[key]) for key in (
                    "group_kind", "group", "model", "attacker", "samples", "coverage",
                    "accuracy", "precision", "recall", "f1", "mcc", "roc_auc",
                )
            )
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_budget_csv(path: Path, attack_budget: Mapping[str, Any]) -> None:
    lines = ["series,budget,count,total,success_rate"]
    for series, rows in attack_budget.items():
        for row in rows:
            lines.append(f"{series},{row['budget']},{row['count']},{row['total']},{row['success_rate']}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_predictions_jsonl(path: Path, records: Sequence[EvalRecord]) -> None:
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")


def write_figures(
    directory: Path,
    report: dict[str, Any],
    records_by_model: Mapping[str, list[EvalRecord]],
    m4_rows_list: Sequence[ValidationRow],
) -> None:
    colours = {
        "indicpass": PALETTE["indicpass"],
        "pcfg": PALETTE["pcfg"],
        "baseline": PALETTE["baseline"],
    }

    # -- ROC / PR curves, M4 ground truth, default budget --------------------
    truth_cache = {
        model: _y_true(records_by_model[model], "m4", report["default_budget"])
        for model in PRIMARY_COLUMNS
    }
    roc_series = [
        ef.LineSeries(
            label=ESTIMATOR_LABELS.get(model, model), colour=colours[model],
            points=em.roc_points(truth_cache[model], _y_score(records_by_model[model])),
        )
        for model in PRIMARY_COLUMNS
    ]
    (directory / "roc.svg").write_text(
        ef.line_chart(
            title="ROC curve -- crackable within 10^8 guesses (M4 ground truth)",
            series=roc_series, x_label="false positive rate", y_label="true positive rate",
            x_range=(0.0, 1.0), y_range=(0.0, 1.0), diagonal=True,
        ),
        encoding="utf-8",
    )

    pr_series = [
        ef.LineSeries(
            label=ESTIMATOR_LABELS.get(model, model), colour=colours[model],
            points=em.pr_points(truth_cache[model], _y_score(records_by_model[model])),
        )
        for model in PRIMARY_COLUMNS
    ]
    (directory / "precision_recall.svg").write_text(
        ef.line_chart(
            title="Precision-recall curve -- crackable within 10^8 guesses (M4)",
            series=pr_series, x_label="recall", y_label="precision",
            x_range=(0.0, 1.0), y_range=(0.0, 1.0),
        ),
        encoding="utf-8",
    )

    # -- confusion matrix, IndicPass, default budget, M4 ---------------------
    default_budget = report["default_budget"]
    indic_default = next(
        r for r in report["classification"]["indicpass"]["m4"] if r["budget"] == default_budget
    )
    (directory / "confusion_matrix.svg").write_text(
        ef.confusion_grid(
            title="IndicPass confusion matrix -- 10^8 guesses, M4 ground truth",
            confusion=indic_default["confusion_matrix"],
        ),
        encoding="utf-8",
    )

    # -- calibration (regression calibration, reused from validation.py) -----
    calibration_series = []
    for model in PRIMARY_COLUMNS:
        entry = row_calibration(m4_rows_list, model, bins=8, points=0)
        points = [(b.mean_predicted, b.mean_observed) for b in entry.bins]
        if points:
            calibration_series.append(
                ef.LineSeries(
                    label=ESTIMATOR_LABELS.get(model, model), colour=colours[model], points=points
                )
            )
    if calibration_series:
        (directory / "calibration.svg").write_text(
            ef.line_chart(
                title="Calibration -- mean predicted vs. mean observed log10 (M4)",
                series=calibration_series, x_label="mean predicted log10 guesses",
                y_label="mean observed log10 rank", diagonal=True,
            ),
            encoding="utf-8",
        )

    # -- attack-budget curve ---------------------------------------------------
    budget_x = [math.log10(b) for b in eb.BUDGETS]
    m4_success = [r["success_rate"] for r in report["attack_budget"]["m4"]]
    m5_success = [r["success_rate"] for r in report["attack_budget"]["m5"]]
    budget_series = [
        ef.LineSeries(
            label="M4 observed", colour=PALETTE["attack"],
            points=list(zip(budget_x, m4_success, strict=True)),
        ),
        ef.LineSeries(
            label="M5 observed", colour=PALETTE["m4"],
            points=list(zip(budget_x, m5_success, strict=True)),
            dashed=True,
        ),
    ]
    for model in PRIMARY_COLUMNS:
        rows = report["attack_budget"][f"predicted_{model}"]
        budget_series.append(
            ef.LineSeries(
                label=f"{ESTIMATOR_LABELS.get(model, model)} predicted", colour=colours[model],
                points=list(zip(budget_x, [r["success_rate"] for r in rows], strict=True)),
                dashed=True,
            )
        )
    (directory / "attack_budget.svg").write_text(
        ef.line_chart(
            title="Attack-budget success rate", series=budget_series,
            x_label="log10 budget", y_label="success rate", y_range=(0.0, 1.0),
        ),
        encoding="utf-8",
    )

    # -- guess-number distribution ---------------------------------------------
    (directory / "guess_distribution.svg").write_text(
        ef.histogram(
            title="Estimated log10 guesses, by estimator",
            series=[
                (
                    ESTIMATOR_LABELS.get(m, m),
                    colours[m],
                    [r.log10_guesses for r in records_by_model[m]],
                )
                for m in PRIMARY_COLUMNS
            ],
            x_label="log10 guesses",
        ),
        encoding="utf-8",
    )

    # -- baseline comparison bars ------------------------------------------
    metrics_for_bars = ("accuracy", "f1", "roc_auc", "pr_auc")
    (directory / "baseline_comparison.svg").write_text(
        grouped_bars(
            title="IndicPass / PCFG / zxcvbn -- 10^8 guesses, M4 ground truth",
            categories=list(metrics_for_bars),
            series=[
                BarSeries(
                    label=ESTIMATOR_LABELS.get(model, model), colour=colours[model],
                    values=[
                        report["baseline_comparison"][metric][model] for metric in metrics_for_bars
                    ],
                )
                for model in PRIMARY_COLUMNS
            ],
        ),
        encoding="utf-8",
    )

    # -- category comparison bars -------------------------------------------
    category_rows = [
        row for row in report["category_metrics"]
        if row["group_kind"] == "category" and row["attacker"] == "m4"
    ]
    by_category: dict[str, dict[str, float | None]] = {}
    for row in category_rows:
        by_category.setdefault(row["group"], {})[row["model"]] = row["f1"]
    categories_present = [c for c in CATEGORIES if c in by_category]
    if categories_present:
        (directory / "category_comparison.svg").write_text(
            grouped_bars(
                title="F1 by category -- 10^8 guesses, M4 ground truth",
                categories=categories_present,
                series=[
                    BarSeries(
                        label=ESTIMATOR_LABELS.get(model, model), colour=colours[model],
                        values=[by_category[c].get(model) for c in categories_present],
                    )
                    for model in PRIMARY_COLUMNS
                ],
            ),
            encoding="utf-8",
        )


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
