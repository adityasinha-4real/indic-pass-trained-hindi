#!/usr/bin/env python
"""Score IndicPass, the PCFG and zxcvbn against an observed cracking order.

    python scripts/reference_attack.py --languages hin
    python scripts/reference_attack.py --languages hin --samples 20 --no-report

Milestones 2 and 3 compared three estimators with each other. This compares all
three against something that is not an estimator: the position at which a fully
specified attacker actually emits each password. See
``src/indicpass/password/reference_attack.py`` for the attack and
``docs/password_strength_design.md`` section 15 for the design.

The corpus is the SAME 1,400 samples Milestones 2 and 3 used -- same generator,
same seed 42, same seven categories -- so the three milestones' numbers sit in
one table. The benchmark is not modified and nothing is re-derived from a
previous report.

Order of operations, which matters
----------------------------------
Every password is scored by all three estimators **once**, before any attack is
built, and the resulting predictions are reused unchanged across every attack
arm. The estimators therefore cannot see the attack, and the attack -- which
imports none of them -- cannot see the estimators. That is the independence the
whole exercise rests on, and it is arranged by construction here rather than
asserted afterwards.

The one caveat is stated in the report itself and is not a bug in the code: the
``frequency`` arm orders its wordlist by the same wordfreq table IndicPass and
the PCFG are built on. It shares evidence with two of the three estimators. The
``shuffled`` and ``length`` arms share none, and a finding is only safe where
the arms agree.

No password is written to either report. Rows are keyed on ``sample_id``, and
the corpus regenerates from committed source and a seed.
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
from indicpass.password.benchmark import (
    CATEGORIES,
    GENERATOR_VERSION,
    BenchmarkSample,
    describe_corpus,
    generate_corpus,
)
from indicpass.password.dictionary import IndicDict
from indicpass.password.meter import IndicPassMeter, describe_dictionaries, describe_pcfg
from indicpass.password.reference_attack import (
    ATTACK_VERSION,
    AttackSettings,
    Lexicon,
    ReferenceAttack,
    dictionary_lexicon_entries,
)
from indicpass.password.validation import (
    ESTIMATOR_COLUMNS,
    ESTIMATOR_LABELS,
    ValidationRow,
    best_by_metric,
    calibration,
    combined_predictions,
    coverage_row,
    metrics,
    stratum_rows,
)

SCRIPT = "reference_attack"

#: Strata that cut across the benchmark categories. Two of the nine required
#: families are properties of the attacker's lexicon or of the case pattern
#: rather than of the generator, so they are measured over the existing corpus
#: instead of being generated -- which is also what leaves the 1,400-sample
#: benchmark untouched.
STRATA: tuple[str, ...] = ("case_variation", "unseen_spelling", "in_lexicon")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="reference_attack.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--samples", type=int, metavar="N", help="Samples per category.")
    parser.add_argument("--seed", type=int, metavar="N", help="Corpus seed.")
    parser.add_argument("--attack-seed", type=int, metavar="N", help="Attack shuffle seed.")
    parser.add_argument("--dictionary", type=Path, metavar="FILE", help="Dictionary to use.")
    parser.add_argument("--report-dir", type=Path, metavar="DIR", help="Where the report lands.")
    parser.add_argument("--no-arms", action="store_true", help="Primary arm only.")
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


# -- arms -------------------------------------------------------------------


@dataclasses.dataclass
class Arm:
    """One attacker configuration, and the question it answers."""

    name: str
    description: str
    #: Independent of the estimators' evidence? ``frequency`` is not.
    independent: bool
    overrides: dict[str, Any] = dataclasses.field(default_factory=dict)
    rows: list[ValidationRow] = dataclasses.field(default_factory=list)
    attack: ReferenceAttack | None = None


#: Every arm is the configured attack with exactly one thing changed. The first
#: is the shipped configuration; the next two are the independence arms, and
#: the rest ask whether a design decision in the ATTACK is load-bearing.
ARMS: tuple[Arm, ...] = (
    Arm(
        "frequency",
        "Wordlist ordered by observed corpus frequency. SHARES EVIDENCE with "
        "IndicPass and the PCFG: both are built on the same wordfreq table.",
        independent=False,
        overrides={"lexicon_order": "frequency"},
    ),
    Arm(
        "shuffled",
        "The same spellings in seeded-shuffle order. No estimator has an "
        "informational advantage. The independence arm.",
        independent=True,
        overrides={"lexicon_order": "shuffled"},
    ),
    Arm(
        "length",
        "Shortest word first, then alphabetical. Frequency-free but not random, "
        "so it separates 'no frequency' from 'no information'.",
        independent=True,
        overrides={"lexicon_order": "length"},
    ),
    Arm(
        "family_rules",
        "Rules ordered by a human-written family precedence instead of by "
        "ascending block size. Does the conclusion depend on the rule order?",
        independent=False,
        overrides={"rule_order": "family"},
    ),
    Arm(
        "budget_1e12",
        "A thousand times smaller attack budget. What does a cheaper attacker "
        "stop being able to reach?",
        independent=False,
        overrides={"max_candidates": 1e12},
    ),
    Arm(
        "no_combinator",
        "word+word rules removed. Isolates how much of the multi-word "
        "category's rank comes from the combinator attack.",
        independent=False,
        overrides={"combinator": False},
    ),
)


# -- scoring ----------------------------------------------------------------


def score_predictions(
    meter: IndicPassMeter, samples: Sequence[BenchmarkSample]
) -> dict[str, dict[str, float]]:
    """Every estimator's verdict on every sample, once.

    Computed before any attack exists and reused unchanged by every arm. An
    estimator that could see the attack would not be being validated by it.
    """
    predictions: dict[str, dict[str, float]] = {}
    for sample in samples:
        result = meter.score(sample.password)
        predictions[sample.sample_id] = combined_predictions(
            indicpass=result.log10_guesses,
            pcfg=result.pcfg_log10_guesses,
            baseline=result.baseline_log10_guesses,
        )
    return predictions


def build_rows(
    attack: ReferenceAttack,
    samples: Sequence[BenchmarkSample],
    predictions: Mapping[str, Mapping[str, float]],
) -> list[ValidationRow]:
    """Rank every sample under *attack* and pair it with its predictions."""
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
                # The generator records its case shape in `construction`, which
                # is published anyway. Reading it there rather than inspecting
                # the password keeps this loop free of anything that could
                # reach a report.
                case_variant=sample.construction.endswith(("/capitalized", "/upper")),
            )
        )
    return rows


def available_columns(rows: Sequence[ValidationRow]) -> list[str]:
    """The estimator columns actually populated, in canonical order."""
    present = {name for row in rows for name in row.predictions}
    return [name for name in ESTIMATOR_COLUMNS if name in present]


# -- report -----------------------------------------------------------------


def build_report(
    *,
    header: dict[str, Any],
    arms: Sequence[Arm],
    reproducibility: dict[str, Any],
) -> dict[str, Any]:
    primary = arms[0]
    rows = primary.rows
    columns = available_columns(rows)
    assert primary.attack is not None

    overall = [metrics(rows, name) for name in columns]
    covered_only = [row for row in rows if row.covered]

    return {
        **header,
        "attack": primary.attack.describe(),
        "primary_arm": primary.name,
        "coverage": {
            "overall": coverage_row(rows),
            "by_category": [coverage_row(rows, name) for name in CATEGORIES],
            "by_stratum": [
                {**coverage_row(stratum_rows(rows, name)), "category": name}
                for name in STRATA
            ],
        },
        "metrics": {
            "overall": [entry.to_dict() for entry in overall],
            "winners": best_by_metric(overall),
            "by_category": {
                category: [
                    metrics(rows, name, category=category).to_dict() for name in columns
                ]
                for category in CATEGORIES
            },
            "by_stratum": {
                stratum: [
                    metrics(stratum_rows(rows, stratum), name).to_dict() for name in columns
                ]
                for stratum in STRATA
            },
        },
        "calibration": {
            "overall": [calibration(rows, name).to_dict() for name in columns],
            "by_category": {
                category: [
                    calibration(rows, name, category=category, bins=5, points=0).to_dict()
                    for name in ("indicpass", "pcfg", "baseline")
                    if name in columns
                ]
                for category in CATEGORIES
            },
        },
        "arms": [
            {
                "name": arm.name,
                "description": arm.description,
                "independent_of_estimator_evidence": arm.independent,
                "attack": {
                    key: value
                    for key, value in (arm.attack.describe() if arm.attack else {}).items()
                    # The full block table is 60 rows and is identical across
                    # most arms; the primary arm's copy above is the reference.
                    if key not in {"blocks"}
                },
                "coverage": coverage_row(arm.rows),
                "coverage_by_category": [
                    coverage_row(arm.rows, name) for name in CATEGORIES
                ],
                "metrics": [
                    metrics(arm.rows, name).to_dict()
                    for name in available_columns(arm.rows)
                ],
                "winners": best_by_metric(
                    [metrics(arm.rows, name) for name in available_columns(arm.rows)]
                ),
            }
            for arm in arms
        ],
        "controls": {
            "random": _random_control(rows),
            "leakage": _leakage_statement(),
            "reproducibility": reproducibility,
            "selection": {
                "covered": len(covered_only),
                "uncovered": len(rows) - len(covered_only),
                "note": (
                    "Every metric is computed on COVERED targets only. An uncovered "
                    "password has no observed rank and is given none. The covered set "
                    "is therefore exactly the set this attack can reach, and the "
                    "metrics are conditional on that -- they say how well an estimator "
                    "predicts the attack WHERE THE ATTACK WORKS, not how well it "
                    "predicts passwords in general."
                ),
            },
        },
        "interpretation_rules": [
            "observed reference rank is a fact about ONE attacker; estimated guess "
            "number is a model output. The two are never the same quantity and are "
            "never averaged together.",
            "A positive signed error means the estimator called a password STRONGER "
            "than this attack found it. That is the dangerous direction.",
            "The frequency arm shares its wordlist ordering evidence with IndicPass "
            "and the PCFG. A result that appears only there is a statement about "
            "shared evidence, not about estimator quality.",
            "Nothing here licenses a claim about real-world cracking accuracy. This "
            "attack has no leaked-password list, no Markov or PCFG guess generator, "
            "no leet substitution, no keyboard walks and no targeted personal data.",
        ],
    }


def _random_control(rows: Sequence[ValidationRow]) -> dict[str, Any]:
    """The control that decides whether any of the rest is believable.

    Two directions, both required. The attack must not reach random strings --
    if it did, its lexicon would be matching noise and every Indic rank would
    be suspect. And the estimators must not price random strings cheaply, which
    is the property Milestones 2 and 3 already measured and this re-checks
    against a population the attack agrees has no structure.
    """
    random_rows = [row for row in rows if row.category == "random"]
    covered = [row for row in random_rows if row.covered]
    return {
        "targets": len(random_rows),
        "covered": len(covered),
        "coverage": round(len(covered) / len(random_rows), 4) if random_rows else 0.0,
        "stem_in_lexicon": sum(1 for row in random_rows if not row.unseen_stem),
        "rules_used": sorted({row.rule for row in covered if row.rule}),
        "note": (
            "The attack should reach almost no random string: its rules are a "
            "wordlist crossed with short suffixes, and a random string is not that. "
            "A high number here would mean the lexicon is matching noise and would "
            "invalidate every rank in the table above."
        ),
    }


def _leakage_statement() -> dict[str, Any]:
    return {
        "candidate_generation_uses_indicpass_scores": False,
        "candidate_generation_uses_pcfg_probabilities": False,
        "candidate_generation_uses_zxcvbn_scores": False,
        "enforced_by": [
            "src/indicpass/password/reference_attack.py imports NOTHING but the "
            "standard library -- not the meter, scoring, matcher, baseline or pcfg, "
            "and not even the dictionary.",
            "tests/test_reference_attack.py parses that module's imports, asserts the "
            "set is stdlib-only, and fails on any estimator module appearing in it.",
            "tests/test_reference_attack.py also ranks a corpus with the meter, the "
            "PCFG and the baseline replaced by objects that raise on any attribute "
            "access, and asserts the ranks are unchanged.",
            "scripts/reference_attack.py scores every password before any attack "
            "object exists, and reuses those predictions unchanged across all arms.",
        ],
        "partial_independence": (
            "Mechanically complete. Evidentially partial: under lexicon_order="
            "frequency the attacker's wordlist order comes from the same wordfreq "
            "table IndicPass prices words with and the PCFG's word distribution is "
            "built from. That arm therefore FAVOURS those two estimators by "
            "construction. The shuffled and length arms remove the shared evidence."
        ),
    }


# -- rendering --------------------------------------------------------------


def _fmt(value: Any, spec: str = ".3f") -> str:
    if value is None:
        return "--"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "inf"
    return format(value, spec) if isinstance(value, (int, float)) else str(value)


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append

    attack = report["attack"]
    settings = attack["settings"]

    add(f"# Reference-attack validation -- {report['language']}")
    add("")
    add(f"Generated {report['generated_at']} from {report['project']} at "
        f"`{report['git_commit'][:12]}`.")
    add("")
    add("This report scores three estimators against an **observed** cracking order. "
        "That order is a fact about one specific attacker, defined below and "
        "reproducible from it. It is **not** a real-world cracking result: no leaked "
        "password corpus is used anywhere in this project, and no claim of real-world "
        "accuracy is made or supported here.")
    add("")

    # -- the attack --------------------------------------------------------
    add("## 1. The reference attack")
    add("")
    add(f"Attack version `{ATTACK_VERSION}`, fingerprint `{attack['fingerprint'][:26]}...`")
    add("")
    add("| setting | value |")
    add("| --- | --- |")
    add(f"| lexicon | {attack['lexicon']['source']}, "
        f"{attack['lexicon']['size']:,} spellings |")
    add(f"| lexicon order | `{settings['lexicon_order']}` "
        f"({attack['lexicon']['frequency_ordered_entries']:,} placed by observed "
        f"frequency, {attack['lexicon']['frequency_ordered_share']:.1%}) |")
    add(f"| rule order | `{settings['rule_order']}` |")
    add(f"| rules placed | {attack['rules_placed']} "
        f"({len(attack['rules_dropped'])} dropped by budget) |")
    add(f"| budget | 10^{settings['log10_max_candidates']:.0f} candidates |")
    add(f"| universe enumerated | {attack['universe_size']:,} "
        f"= 10^{attack['log10_universe_size']:.2f} |")
    add(f"| digits / symbol+digits | up to {settings['max_digits']} / "
        f"{settings['max_symbol_digits']} |")
    add(f"| years | {settings['year_range'][0]}-{settings['year_range'][1]} |")
    add(f"| symbols | {settings['symbol_count']} (`{settings['symbols']}`) |")
    add(f"| combinator (word+word) | {settings['combinator']} |")
    add(f"| seed | {settings['seed']} |")
    add("")
    add("The first ten rule blocks, in enumeration order:")
    add("")
    add("| # | rule | block size | candidates before it |")
    add("| --- | --- | ---: | ---: |")
    for index, block in enumerate(attack["blocks"][:10], start=1):
        add(f"| {index} | `{block['name']}` | {block['size']:,} | {block['offset']:,} |")
    add("")
    if attack["rules_dropped"]:
        add(f"Dropped by the budget: {', '.join(f'`{n}`' for n in attack['rules_dropped'])}.")
        add("")

    # -- coverage ----------------------------------------------------------
    coverage = report["coverage"]
    add("## 2. Coverage")
    add("")
    add("An uncovered password is given **no rank**. It is never assigned the universe "
        "size, a censored bound, or any substituted value, and it contributes to this "
        "table and to nothing else.")
    add("")
    add("| category | targets | covered | coverage | median log10 rank | mean log10 rank |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in coverage["by_category"]:
        add(f"| {row['category']} | {row['targets']} | {row['covered']} | "
            f"{row['coverage']:.1%} | {_fmt(row.get('median_log10_rank'), '.2f')} | "
            f"{_fmt(row.get('mean_log10_rank'), '.2f')} |")
    total = coverage["overall"]
    add(f"| **all** | {total['targets']} | {total['covered']} | {total['coverage']:.1%} | "
        f"{_fmt(total.get('median_log10_rank'), '.2f')} | "
        f"{_fmt(total.get('mean_log10_rank'), '.2f')} |")
    add("")
    add("The two families that are not benchmark categories -- case variation and "
        "unseen spellings -- are strata over the same 1,400 samples, because both are "
        "properties of the attacker's lexicon or of the generator's case roll rather "
        "than of a category:")
    add("")
    add("| stratum | targets | covered | coverage | median log10 rank |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for row in coverage["by_stratum"]:
        add(f"| {row['category']} | {row['targets']} | {row['covered']} | "
            f"{row['coverage']:.1%} | {_fmt(row.get('median_log10_rank'), '.2f')} |")
    add("")

    # -- metrics -----------------------------------------------------------
    add("## 3. Estimators against the observed rank")
    add("")
    add("`error = predicted log10 guesses - observed log10 rank`. **Positive means the "
        "estimator called the password stronger than this attack found it** -- the "
        "dangerous direction for a meter.")
    add("")
    add("| estimator | n | Spearman | Pearson | mean err | median err | MAE | "
        "med abs | RMSE | +-0.5 | +-1.0 | direction |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
    for entry in report["metrics"]["overall"]:
        add(
            f"| {entry['label']} | {entry['samples']} | {_fmt(entry['spearman'])} | "
            f"{_fmt(entry['pearson'])} | {entry['mean_signed_error']:+.3f} | "
            f"{entry['median_signed_error']:+.3f} | {entry['mean_absolute_error']:.3f} | "
            f"{entry['median_absolute_error']:.3f} | {entry['rmse']:.3f} | "
            f"{entry['within_0.5_log10']:.1%} | {entry['within_1.0_log10']:.1%} | "
            f"{entry['direction']} |"
        )
    add("")
    add("Which estimator wins under each metric -- reported as a table rather than a "
        "ranking, because they disagree and the disagreement is a result:")
    add("")
    add("| metric | winner | value |")
    add("| --- | --- | ---: |")
    for metric, winner in report["metrics"]["winners"].items():
        if winner is None:
            add(f"| {metric} | -- | -- |")
        else:
            add(f"| {metric} | {winner['label']} | {_fmt(winner['value'])} |")
    add("")

    # -- per category ------------------------------------------------------
    add("### 3.1 By category")
    add("")
    add("| category | estimator | n | Spearman | mean err | MAE | +-1.0 |")
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for category in CATEGORIES:
        entries = report["metrics"]["by_category"].get(category, [])
        for entry in entries:
            if entry["estimator"] not in ("indicpass", "pcfg", "baseline"):
                continue
            add(
                f"| {category if entry['estimator'] == 'indicpass' else ''} | "
                f"{entry['label']} | {entry['samples']} | {_fmt(entry['spearman'])} | "
                f"{entry['mean_signed_error']:+.3f} | {entry['mean_absolute_error']:.3f} | "
                f"{entry['within_1.0_log10']:.1%} |"
            )
    add("")

    add("### 3.2 By stratum")
    add("")
    add("| stratum | estimator | n | Spearman | mean err | MAE | +-1.0 |")
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for stratum in STRATA:
        for entry in report["metrics"]["by_stratum"].get(stratum, []):
            if entry["estimator"] not in ("indicpass", "pcfg", "baseline"):
                continue
            add(
                f"| {stratum if entry['estimator'] == 'indicpass' else ''} | "
                f"{entry['label']} | {entry['samples']} | {_fmt(entry['spearman'])} | "
                f"{entry['mean_signed_error']:+.3f} | {entry['mean_absolute_error']:.3f} | "
                f"{entry['within_1.0_log10']:.1%} |"
            )
    add("")

    # -- calibration -------------------------------------------------------
    add("## 4. Calibration")
    add("")
    add("Ordinary least squares of observed `log10` rank on predicted `log10` guesses. "
        "Slope 1 and intercept 0 is perfect calibration **against this attack**. A "
        "slope below one means the estimator spreads passwords over fewer orders of "
        "magnitude than the attack does.")
    add("")
    add("| estimator | n | slope | intercept | r^2 |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for entry in report["calibration"]["overall"]:
        add(f"| {entry['label']} | {entry['samples']} | {_fmt(entry['slope'])} | "
            f"{_fmt(entry['intercept'])} | {_fmt(entry['r_squared'])} |")
    add("")
    add("Bias by decile of prediction, for the three primary estimators. "
        "`bias = mean predicted - mean observed`:")
    add("")
    for entry in report["calibration"]["overall"]:
        if entry["estimator"] not in ("indicpass", "pcfg", "baseline") or not entry["bins"]:
            continue
        add(f"**{entry['label']}**")
        add("")
        add("| decile | n | predicted range | mean predicted | mean observed | bias |")
        add("| ---: | ---: | --- | ---: | ---: | ---: |")
        for chunk in entry["bins"]:
            add(f"| {chunk['bin']} | {chunk['samples']} | "
                f"{chunk['predicted_low']:.2f}-{chunk['predicted_high']:.2f} | "
                f"{chunk['mean_predicted']:.2f} | {chunk['mean_observed']:.2f} | "
                f"{chunk['mean_bias']:+.2f} |")
        add("")
    add("The `points` array in the JSON carries thinned `(predicted, observed)` pairs "
        "for plotting. A pair of numbers identifies no password.")
    add("")

    # -- arms --------------------------------------------------------------
    add("## 5. Does the answer depend on the attacker?")
    add("")
    add("Each arm is the attack above with exactly one thing changed. The `frequency` "
        "arm shares its wordlist ordering with IndicPass and the PCFG; `shuffled` and "
        "`length` share nothing. **A conclusion is only safe where the arms agree.**")
    add("")
    add("| arm | independent | coverage | log10 universe | "
        "Spearman M2 / PCFG / zxcvbn | MAE M2 / PCFG / zxcvbn |")
    add("| --- | --- | ---: | ---: | --- | --- |")
    for arm in report["arms"]:
        by_name = {entry["estimator"]: entry for entry in arm["metrics"]}
        spear = " / ".join(
            _fmt(by_name.get(name, {}).get("spearman"), ".3f")
            for name in ("indicpass", "pcfg", "baseline")
        )
        mae = " / ".join(
            _fmt(by_name.get(name, {}).get("mean_absolute_error"), ".2f")
            for name in ("indicpass", "pcfg", "baseline")
        )
        universe = arm["attack"].get("log10_universe_size")
        add(f"| `{arm['name']}` | "
            f"{'yes' if arm['independent_of_estimator_evidence'] else 'NO'} | "
            f"{arm['coverage']['coverage']:.1%} | {_fmt(universe, '.2f')} | "
            f"{spear} | {mae} |")
    add("")
    for arm in report["arms"]:
        add(f"* **`{arm['name']}`** -- {arm['description']}")
    add("")

    # -- controls ----------------------------------------------------------
    controls = report["controls"]
    add("## 6. Controls")
    add("")
    control = controls["random"]
    add("### 6.1 Random")
    add("")
    add(f"The attack reaches **{control['covered']} of {control['targets']}** random "
        f"controls ({control['coverage']:.1%}). The lexicon can produce the leading "
        f"letter run of {control['stem_in_lexicon']} of the {control['targets']} at "
        f"all.")
    add("")
    add(control["note"])
    add("")

    leakage = controls["leakage"]
    add("### 6.2 Leakage and independence")
    add("")
    add("| the candidate generator uses ... | |")
    add("| --- | --- |")
    add(f"| IndicPass scores | {leakage['candidate_generation_uses_indicpass_scores']} |")
    add(f"| PCFG probabilities | {leakage['candidate_generation_uses_pcfg_probabilities']} |")
    add(f"| zxcvbn scores | {leakage['candidate_generation_uses_zxcvbn_scores']} |")
    add("")
    for item in leakage["enforced_by"]:
        add(f"* {item}")
    add("")
    add(f"**Partial independence.** {leakage['partial_independence']}")
    add("")

    repro = controls["reproducibility"]
    add("### 6.3 Reproducibility")
    add("")
    add("| quantity | identical across two independent builds |")
    add("| --- | --- |")
    add(f"| lexicon fingerprint | {repro['lexicon_fingerprint_matches']} |")
    add(f"| attack fingerprint | {repro['attack_fingerprint_matches']} |")
    add(f"| block programme | {repro['blocks_match']} |")
    add(f"| every target rank | {repro['ranks_match']} ({repro['targets']} targets) |")
    add(f"| aggregate metrics | {repro['metrics_match']} |")
    add("")
    add(f"Attack fingerprint: `{repro['attack_fingerprint']}`")
    add("")

    selection = controls["selection"]
    add("### 6.4 Selection")
    add("")
    add(f"{selection['covered']} covered, {selection['uncovered']} uncovered. "
        f"{selection['note']}")
    add("")

    # -- rules -------------------------------------------------------------
    add("## 7. How to read this")
    add("")
    for rule in report["interpretation_rules"]:
        add(f"* {rule}")
    add("")
    add("---")
    add("")
    add(f"Corpus: {report['corpus']['total_samples']} generated samples, generator "
        f"version {report['corpus']['generator_version']}, seed {report['corpus_seed']}. "
        "No password is stored in this report; rows are keyed on `sample_id` and the "
        "corpus regenerates from committed source and that seed.")
    add("")
    return "\n".join(lines) + "\n"


def print_console(report: dict[str, Any]) -> None:
    attack = report["attack"]
    width = 92
    print(f"\n{'=' * width}")
    print("REFERENCE-ATTACK VALIDATION -- observed rank vs estimated guesses")
    print(f"{'=' * width}")
    print(f"  attack        {attack['rules_placed']} rules, universe 10^"
          f"{attack['log10_universe_size']:.2f}, lexicon {attack['lexicon']['size']:,} "
          f"({attack['settings']['lexicon_order']})")
    total = report["coverage"]["overall"]
    print(f"  coverage      {total['covered']}/{total['targets']} "
          f"({total['coverage']:.1%})")
    print()
    print(f"  {'estimator':<22}{'n':>6}{'rho':>8}{'mean err':>10}"
          f"{'MAE':>8}{'RMSE':>8}{'+-1.0':>8}")
    for entry in report["metrics"]["overall"]:
        print(f"  {entry['label']:<22}{entry['samples']:>6}"
              f"{_fmt(entry['spearman']):>8}{entry['mean_signed_error']:>+10.3f}"
              f"{entry['mean_absolute_error']:>8.3f}{entry['rmse']:>8.3f}"
              f"{entry['within_1.0_log10']:>7.0%} ")
    print()
    print("  winner by metric:")
    for metric, winner in report["metrics"]["winners"].items():
        label = winner["label"] if winner else "--"
        value = _fmt(winner["value"]) if winner else "--"
        print(f"    {metric:<26}{label:<22}{value}")
    print()
    print(f"  {'arm':<16}{'indep':>7}{'cover':>8}   rho  M2 / PCFG / zxcvbn")
    for arm in report["arms"]:
        by_name = {entry["estimator"]: entry for entry in arm["metrics"]}
        spear = " / ".join(
            _fmt(by_name.get(name, {}).get("spearman"), ".3f")
            for name in ("indicpass", "pcfg", "baseline")
        )
        print(f"  {arm['name']:<16}"
              f"{'yes' if arm['independent_of_estimator_evidence'] else 'NO':>7}"
              f"{arm['coverage']['coverage']:>8.1%}   {spear}")
    print()
    control = report["controls"]["random"]
    print(f"  random control: attack reaches {control['covered']}/{control['targets']} "
          f"({control['coverage']:.1%})")
    repro = report["controls"]["reproducibility"]
    print(f"  reproducibility: ranks identical {repro['ranks_match']}, "
          f"fingerprint {repro['attack_fingerprint_matches']}")
    print()


# -- main -------------------------------------------------------------------


def _settings(section: Mapping[str, Any], overrides: Mapping[str, Any]) -> AttackSettings:
    return dataclasses.replace(AttackSettings.from_config(section), **dict(overrides))


def _build_attack(
    entries: Sequence[tuple[str, int | None]], settings: AttackSettings
) -> ReferenceAttack:
    lexicon = Lexicon.build(
        entries,
        order=settings.lexicon_order,
        seed=settings.seed,
        size=settings.lexicon_size,
    )
    return ReferenceAttack.build(lexicon, settings)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error(
            "The reference attack is built from one lexicon. Pass --languages hin."
        )
        return 2
    language = languages[0]

    section = config.password_section("reference_attack")
    evaluation = config.password_section("evaluation")
    attack_evaluation = dict(section.get("evaluation") or {})
    dictionary_config = config.password_section("dictionary")
    tier_order = [str(tier["name"]) for tier in (dictionary_config.get("tiers") or [])]

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
        logger.error(
            "No baseline loaded. The validation compares three estimators; running it "
            "with two would answer a different question. Install zxcvbn."
        )
        return 2
    if meter.pcfg is None:
        logger.error(
            "No PCFG loaded. Train one with scripts/train_pcfg.py --languages hin, or "
            "set pcfg.enabled: true in config/password.yaml."
        )
        return 2

    samples = generate_corpus(seed=seed, samples_per_category=per_category)
    logger.info("Corpus: %d samples across %d categories", len(samples), len(CATEGORIES))

    # Scored FIRST, before any attack object exists. See the module docstring.
    started = time.perf_counter()
    predictions = score_predictions(meter, samples)
    logger.info(
        "Scored %d samples with three estimators in %.1fs",
        len(predictions),
        time.perf_counter() - started,
    )

    entries = dictionary_lexicon_entries(dictionary)
    logger.info("Lexicon candidates: %d lower-case spellings", len(entries))

    if args.attack_seed is not None:
        section = {**section, "seed": args.attack_seed}

    arms = [dataclasses.replace(arm, rows=[], attack=None) for arm in ARMS]
    if args.no_arms:
        arms = arms[:1]

    for arm in arms:
        started = time.perf_counter()
        attack = _build_attack(entries, _settings(section, arm.overrides))
        arm.attack = attack
        arm.rows = build_rows(attack, samples, predictions)
        covered = sum(1 for row in arm.rows if row.covered)
        logger.info(
            "%-16s %2d rules, universe 10^%.2f, covered %d/%d in %.1fs",
            arm.name,
            len(attack.blocks),
            math.log10(attack.universe_size),
            covered,
            len(arm.rows),
            time.perf_counter() - started,
        )

    # -- reproducibility: build the primary arm again, from scratch ---------
    primary = arms[0]
    assert primary.attack is not None
    logger.info("Rebuilding the primary arm to check reproducibility")
    again = _build_attack(entries, _settings(section, primary.overrides))
    again_rows = build_rows(again, samples, predictions)
    columns = available_columns(primary.rows)
    reproducibility = {
        "targets": len(primary.rows),
        "lexicon_fingerprint_matches": (
            again.lexicon.fingerprint() == primary.attack.lexicon.fingerprint()
        ),
        "attack_fingerprint_matches": again.fingerprint() == primary.attack.fingerprint(),
        "attack_fingerprint": primary.attack.fingerprint(),
        "blocks_match": [b.to_dict() for b in again.blocks]
        == [b.to_dict() for b in primary.attack.blocks],
        "ranks_match": [row.reference_rank for row in again_rows]
        == [row.reference_rank for row in primary.rows],
        "metrics_match": [metrics(again_rows, name).to_dict() for name in columns]
        == [metrics(primary.rows, name).to_dict() for name in columns],
        "note": (
            "Two independent builds from the same seed and configuration, in the same "
            "process but sharing no state: a fresh lexicon, a fresh rule programme and "
            "a fresh ranking pass."
        ),
    }

    header = {
        "report": "reference_attack",
        "attack_version": ATTACK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(config.root),
        "project": f"{config.name} v{config.version}",
        "language": language.code,
        "corpus_seed": seed,
        "corpus": {**describe_corpus(samples), "generator_version": GENERATOR_VERSION},
        "dictionaries": describe_dictionaries(meter),
        "pcfg": describe_pcfg(meter),
        "baseline_name": meter.baseline.name,
        "estimator_columns": {name: ESTIMATOR_LABELS[name] for name in columns},
    }

    report = build_report(header=header, arms=arms, reproducibility=reproducibility)
    print_console(report)

    if args.no_report:
        return 0

    directory = (
        config.resolve(args.report_dir) if args.report_dir else config.ensure_dir("reports")
    )
    directory.mkdir(parents=True, exist_ok=True)
    prefix = attack_evaluation.get("report_prefix", "reference_attack")
    base = directory / f"{prefix}_{language.code}"
    base.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render(report), encoding="utf-8")
    logger.info("Report written to %s", config.relative(base.with_suffix(".md")))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
