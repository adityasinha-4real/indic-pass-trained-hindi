#!/usr/bin/env python
"""Score the estimators against an attacker that can reach out-of-lexicon spellings.

    python scripts/milestone5_oov_attack.py --languages hin
    python scripts/milestone5_oov_attack.py --languages hin --samples 20 --no-report

Milestone 4 measured an observed rank for 528 of the 1,400 benchmark targets and
could not reach the other 872, because its universe is a wordlist and those
passwords are built from spellings the wordlist lacks. Milestone 3's central
claim is about exactly those 872. This script tests it, against the attacker in
``src/indicpass/password/character_attack.py`` whose universe is every
lower-case letter string within a stated length and cost bound -- so an
out-of-lexicon spelling is reachable on the same terms as one in the dictionary.

The corpus is the SAME 1,400 samples Milestones 2, 3 and 4 used: same generator,
same seed 42, same seven categories. It is not modified, not extended and not
filtered, and nothing is re-derived from a previous report.

Order of operations, which matters
----------------------------------
Every password is scored by all three estimators **once**, before any attack
object is constructed, and the resulting predictions are reused unchanged across
every arm. The estimators therefore cannot see the attack, and the attack --
which imports none of them -- cannot see the estimators. ``tests/`` asserts the
ordering directly, as well as parsing the attack module's imports and ranking a
corpus with the estimators replaced by objects that raise on contact.

The caveat is stated in the report rather than hidden: under ``model=indicdict``
the character model is trained on the same romanized spellings the PCFG's own
n-gram is trained on. Different order, different smoothing, different code --
the same evidence. The ``uniform`` arm removes it entirely, and a finding is
only safe where the two agree.

No password is written to either report. Rows are keyed on ``sample_id`` and the
corpus regenerates from committed source and a seed.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import subprocess
import sys
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
from indicpass.password.character_attack import (
    ATTACK_VERSION,
    CharacterAttack,
    CharacterAttackRank,
    CharacterAttackSettings,
    CharacterModel,
    coverage,
    dictionary_stem_corpus,
)
from indicpass.password.dictionary import IndicDict
from indicpass.password.meter import IndicPassMeter, describe_dictionaries, describe_pcfg
from indicpass.password.oov import (
    INDIC_CATEGORIES,
    MAX_INFLECTION_LENGTH,
    MIN_EVIDENCE_LENGTH,
    OOV_PARTITIONS,
    PARTITIONS,
    REPORT_GROUPS,
    VARIANT_RULES,
    OovTargetRow,
    Taxonomy,
    group_rows,
    partition_counts,
)
from indicpass.password.uncertainty import BOOTSTRAP_STATISTICS, bootstrap_group
from indicpass.password.validation import (
    ESTIMATOR_COLUMNS,
    ESTIMATOR_LABELS,
    PRIMARY_ESTIMATORS,
    ValidationRow,
    best_by_metric,
    calibration,
    combined_predictions,
    metrics,
)

SCRIPT = "milestone5_oov_attack"

#: Report keys that legitimately differ between two runs and are therefore
#: excluded from the byte-identity check. Everything else must match exactly.
VOLATILE_KEYS: frozenset[str] = frozenset({"generated_at", "reproducibility"})

#: The paired differences the bootstrap reports. The first is the milestone's
#: question; the other two are what it has to be read against.
ESTIMATOR_PAIRS: tuple[tuple[str, str], ...] = (
    ("pcfg", "indicpass"),
    ("pcfg", "baseline"),
    ("indicpass", "baseline"),
)

#: Populations small enough that a table of them would be mostly noise are still
#: listed, with their n, because omitting them would be a selection.
HEADLINE_GROUPS: tuple[str, ...] = ("all", "in_lexicon", "oov", "oov_indic")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="milestone5_oov_attack.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--samples", type=int, metavar="N", help="Samples per category.")
    parser.add_argument("--seed", type=int, metavar="N", help="Corpus seed.")
    parser.add_argument("--dictionary", type=Path, metavar="FILE", help="Dictionary to use.")
    parser.add_argument("--report-dir", type=Path, metavar="DIR", help="Where the report lands.")
    parser.add_argument("--resamples", type=int, metavar="N", help="Bootstrap resamples.")
    parser.add_argument("--no-arms", action="store_true", help="Primary arm only.")
    parser.add_argument("--no-report", action="store_true", help="Print only; write no files.")
    parser.add_argument(
        "--canonical-out",
        type=Path,
        metavar="FILE",
        help="Write the volatile-free report payload here and stop. Used by the "
        "reproducibility check, which runs this script a second time in a separate "
        "process and compares the bytes.",
    )
    parser.add_argument(
        "--no-repro-check",
        action="store_true",
        help="Skip the second process. Set automatically for the child run.",
    )
    return parser


def git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def corpus_digest(samples: Sequence[BenchmarkSample]) -> str:
    """SHA-256 over the corpus itself.

    Over the passwords, deliberately: the digest is what proves two runs scored
    the same 1,400 strings, and a hash of them is not a list of them. Nothing
    else in this file touches a password.
    """
    digest = hashlib.sha256()
    digest.update(f"{GENERATOR_VERSION}\n".encode())
    for sample in samples:
        digest.update(f"{sample.sample_id}\t{sample.category}\t{sample.password}\n".encode())
    return f"sha256:{digest.hexdigest()}"


# -- arms -------------------------------------------------------------------


@dataclasses.dataclass
class Arm:
    """One attacker configuration, and the question it answers."""

    name: str
    description: str
    #: Does this arm's ordering share training evidence with an estimator?
    independent: bool
    overrides: dict[str, Any] = dataclasses.field(default_factory=dict)
    rows: list[OovTargetRow] = dataclasses.field(default_factory=list)
    attack: CharacterAttack | None = None


#: Every arm is the configured attack with exactly one thing changed. The first
#: is the shipped configuration; the second is the arm that shares no evidence
#: with any estimator, and the rest ask whether an assumption in the ATTACK is
#: load-bearing.
ARMS: tuple[Arm, ...] = (
    Arm(
        "indicdict",
        "Character model trained on the dictionary's romanized spellings. SHARES "
        "TRAINING EVIDENCE with the PCFG's n-gram: same spellings, different order, "
        "smoothing and implementation.",
        independent=False,
        overrides={"model": "indicdict"},
    ),
    Arm(
        "uniform",
        "No character statistics at all: every symbol costs the same, so the ordering "
        "is length then lexicographic. No estimator has an informational advantage. "
        "The independence arm, and the null the character model is measured against.",
        independent=True,
        overrides={"model": "uniform"},
    ),
    Arm(
        "holdout_half",
        "Trained on a seeded half of the spellings. Does the attack's reach come from "
        "the PARTICULAR words the dictionary holds, or from the shape of the language?",
        independent=False,
        overrides={"training_share": 0.5},
    ),
    Arm(
        "order_2",
        "A bigram model instead of a trigram. How much of the ordering survives a "
        "weaker character model?",
        independent=False,
        overrides={"order": 2},
    ),
    Arm(
        "smoothing_0.1",
        "Additive smoothing at 0.1 instead of 1.0. alpha is an assumption; this is the "
        "measurement of how far it moves the answer.",
        independent=False,
        overrides={"smoothing": 0.1},
    ),
    Arm(
        "precision_0.5",
        "A coarser level quantum: half a log10 unit instead of a quarter. Quantisation "
        "is what makes the universe countable, so its granularity is load-bearing by "
        "construction and has to be measured rather than argued about.",
        independent=False,
        overrides={"precision": 0.5},
    ),
    Arm(
        "budget_1e12",
        "A ten-thousand-times smaller budget. What stops being reachable when the "
        "attacker can afford less?",
        independent=False,
        overrides={"max_candidates": 1e12},
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
    attack: CharacterAttack,
    samples: Sequence[BenchmarkSample],
    taxonomy: Taxonomy,
    predictions: Mapping[str, Mapping[str, float]],
) -> list[OovTargetRow]:
    """Rank every sample under *attack*, and pair it with its class and predictions."""
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


def available_columns(rows: Sequence[OovTargetRow]) -> list[str]:
    """The estimator columns actually populated, in canonical order."""
    present = {name for row in rows for name in row.predictions}
    return [name for name in ESTIMATOR_COLUMNS if name in present]


def validation_rows(rows: Sequence[OovTargetRow]) -> list[ValidationRow]:
    return [row.as_validation_row() for row in rows]


def coverage_of(rows: Sequence[OovTargetRow], label: str) -> dict[str, Any]:
    """Reachability for one population, with the median depth it was reached at."""
    reached = [row for row in rows if row.reachable and row.log10_rank is not None]
    depths = sorted(float(row.log10_rank) for row in reached)  # type: ignore[arg-type]
    reasons: dict[str, int] = {}
    for row in rows:
        if row.reason:
            reasons[row.reason] = reasons.get(row.reason, 0) + 1
    return {
        "population": label,
        "targets": len(rows),
        "in_lexicon": sum(1 for row in rows if row.in_lexicon),
        "reachable": len(reached),
        "coverage": round(len(reached) / len(rows), 4) if rows else 0.0,
        "median_log10_rank": round(depths[len(depths) // 2], 4) if depths else None,
        "mean_log10_rank": (
            round(sum(depths) / len(depths), 4) if depths else None
        ),
        "min_log10_rank": round(depths[0], 4) if depths else None,
        "max_log10_rank": round(depths[-1], 4) if depths else None,
        "exclusion_reasons": dict(sorted(reasons.items(), key=lambda item: (-item[1], item[0]))),
    }


# -- report -----------------------------------------------------------------


def build_report(
    *,
    header: dict[str, Any],
    arms: Sequence[Arm],
    bootstrap: Mapping[str, Any],
    reproduction_command: str,
) -> dict[str, Any]:
    primary = arms[0]
    rows = primary.rows
    columns = available_columns(rows)
    assert primary.attack is not None
    plain = validation_rows(rows)

    grouped = {group: group_rows(rows, group) for group in REPORT_GROUPS}

    return {
        **header,
        "attack": primary.attack.describe(),
        "primary_arm": primary.name,
        "taxonomy": _taxonomy_block(rows),
        "coverage": {
            "overall": coverage_of(rows, "all"),
            "by_category": [
                coverage_of([row for row in rows if row.category == name], name)
                for name in CATEGORIES
            ],
            "by_group": [
                coverage_of(grouped[group], group) for group in REPORT_GROUPS
            ],
            "shapes": coverage([_rank_of(row) for row in rows])["shapes"],
        },
        "metrics": {
            "by_group": {
                group: [
                    metrics(validation_rows(grouped[group]), name).to_dict()
                    for name in columns
                ]
                for group in REPORT_GROUPS
            },
            "winners": {
                group: best_by_metric(
                    [metrics(validation_rows(grouped[group]), name) for name in columns]
                )
                for group in REPORT_GROUPS
            },
            "by_category": {
                category: [
                    metrics(plain, name, category=category).to_dict() for name in columns
                ]
                for category in CATEGORIES
            },
        },
        "calibration": {
            "by_group": {
                group: [
                    calibration(
                        validation_rows(grouped[group]), name, bins=5, points=0
                    ).to_dict()
                    for name in PRIMARY_ESTIMATORS
                    if name in columns
                ]
                for group in REPORT_GROUPS
            },
            "overall_points": [
                calibration(plain, name).to_dict()
                for name in PRIMARY_ESTIMATORS
                if name in columns
            ],
        },
        "uncertainty": bootstrap,
        "m2_vs_m3": _m2_vs_m3(grouped, bootstrap),
        "arms": [
            {
                "name": arm.name,
                "description": arm.description,
                "independent_of_estimator_evidence": arm.independent,
                "attack": {
                    key: value
                    for key, value in (arm.attack.describe() if arm.attack else {}).items()
                    # The shape table is 33 rows and identical across most arms;
                    # the primary arm's copy above is the reference.
                    if key != "shapes"
                },
                "coverage": {
                    group: coverage_of(group_rows(arm.rows, group), group)
                    for group in HEADLINE_GROUPS
                },
                "metrics": {
                    group: [
                        metrics(validation_rows(group_rows(arm.rows, group)), name).to_dict()
                        for name in PRIMARY_ESTIMATORS
                        if name in columns
                    ]
                    for group in HEADLINE_GROUPS
                },
            }
            for arm in arms
        ],
        "controls": _controls(rows, arms),
        "targets": [row.to_dict() for row in rows],
        "limitations": LIMITATIONS,
        "interpretation_rules": INTERPRETATION_RULES,
        "reproduction": {
            "command": reproduction_command,
            "note": (
                "Reproduces this report from committed source. The corpus is generated "
                "from the seed, the character model is refitted from the dictionary "
                "file, and the attack is rebuilt from the settings above."
            ),
        },
    }


def _rank_of(row: OovTargetRow) -> CharacterAttackRank:
    """The row's attack result, back in the attacker's own shape.

    Only so :func:`coverage` -- which lives beside the attack and knows nothing
    about partitions -- can summarise the shapes that did the reaching.
    """
    return CharacterAttackRank(
        reachable=row.reachable,
        rank=row.rank,
        log10_rank=row.log10_rank,
        shape=row.shape,
        level=row.level,
        reason=row.reason,
    )


def _taxonomy_block(rows: Sequence[OovTargetRow]) -> dict[str, Any]:
    return {
        "partitions": partition_counts(rows),
        "rules": [
            "The partition is applied to the target's leading run of ASCII letters, "
            "lower-cased -- which is exactly the stem the attack has to produce.",
            "random -> random_control; english -> english_control; mixed -> "
            "mixed_construction. Controls and two-word bodies are never folded into "
            "a lexical population.",
            "Otherwise: in the dictionary -> indic_in_lexicon. (The `in_lexicon` GROUP "
            "is different and wider: plain dictionary membership across all seven "
            "categories. The two are spelled apart so a table cannot mean the wrong one.)",
            "Otherwise, first match wins: in the benchmark's name and place bank -> "
            "oov_name; a documented respelling is in the dictionary -> "
            "oov_spelling_variant; a known prefix of at least "
            f"{MIN_EVIDENCE_LENGTH} characters leaves at most {MAX_INFLECTION_LENGTH} "
            "over -> oov_morphological_variant; a known word of at least "
            f"{MIN_EVIDENCE_LENGTH} characters occurs inside it -> oov_stem_suffix; "
            "otherwise oov_other.",
        ],
        "variant_rules": [f"{source}->{target}" for source, target in VARIANT_RULES],
        "status": (
            "A classification HEURISTIC, not a linguistic claim. It will mislabel some "
            "targets in both directions. Nothing in the headline finding depends on it: "
            "the in_lexicon / oov split is plain dictionary membership, which is exact, "
            "and the partitions only keep the OOV population from being reported as one "
            "undifferentiated lump."
        ),
        "indic_categories": list(INDIC_CATEGORIES),
        "oov_partitions": list(OOV_PARTITIONS),
    }


def _m2_vs_m3(
    grouped: Mapping[str, Sequence[OovTargetRow]], bootstrap: Mapping[str, Any]
) -> dict[str, Any]:
    """The milestone's question, in one table, with its interval beside it."""
    table = []
    for group in REPORT_GROUPS:
        rows = validation_rows(grouped[group])
        m2 = metrics(rows, "indicpass")
        m3 = metrics(rows, "pcfg")
        if m2.samples == 0:
            continue
        interval = (
            bootstrap.get(group, {}).get("differences", {}).get("pcfg-minus-indicpass", {})
        )
        table.append(
            {
                "group": group,
                "samples": m2.samples,
                "indicpass": m2.to_dict(),
                "pcfg": m3.to_dict(),
                "differences": {
                    statistic: interval.get(statistic) for statistic in BOOTSTRAP_STATISTICS
                },
            }
        )
    return {
        "table": table,
        "note": (
            "difference = PCFG (M3) minus IndicPass (M2), on the SAME targets. The "
            "bootstrap is paired: both estimators are scored on each resample, so the "
            "interval is on their difference and not on two independent quantities. "
            "For an error metric a negative difference favours the PCFG; for a "
            "correlation a positive one does. `higher_is_better` on each row says which."
        ),
    }


def _controls(rows: Sequence[OovTargetRow], arms: Sequence[Arm]) -> dict[str, Any]:
    random_rows = [row for row in rows if row.category == "random"]
    oov_indic = group_rows(rows, "oov_indic")
    in_lexicon = group_rows(rows, "in_lexicon")

    def median_depth(selected: Sequence[OovTargetRow]) -> float | None:
        depths = sorted(
            float(row.log10_rank) for row in selected if row.reachable and row.log10_rank
        )
        return round(depths[len(depths) // 2], 4) if depths else None

    random_depth = median_depth(random_rows)
    oov_depth = median_depth(oov_indic)
    return {
        "separation": {
            "median_log10_rank_random": random_depth,
            "median_log10_rank_oov_indic": oov_depth,
            "median_log10_rank_in_lexicon": median_depth(in_lexicon),
            "orders_of_magnitude_separation": (
                round(random_depth - oov_depth, 4)
                if random_depth is not None and oov_depth is not None
                else None
            ),
            "note": (
                "Unlike Milestone 4, this attack CAN reach a random lower-case string: "
                "its universe is every letter string within the bounds. So the control "
                "is not 'does it reach random strings' but 'how much later'. A "
                "character model that carries real information about Romanized Hindi "
                "must put an out-of-lexicon Hindi spelling orders of magnitude ahead of "
                "a random string. A separation near zero would mean the model is "
                "matching noise and would invalidate every OOV rank in this report."
            ),
        },
        "random": {
            "targets": len(random_rows),
            "reachable": sum(1 for row in random_rows if row.reachable),
            "coverage": (
                round(sum(1 for row in random_rows if row.reachable) / len(random_rows), 4)
                if random_rows
                else 0.0
            ),
            "median_log10_rank": random_depth,
        },
        "leakage": _leakage_statement(),
        "selection": {
            "targets": len(rows),
            "reachable": sum(1 for row in rows if row.reachable),
            "unreachable": sum(1 for row in rows if not row.reachable),
            "note": (
                "Every metric is computed on REACHABLE targets only. An unreachable "
                "password has no observed rank and is given none -- not the universe "
                "size, not a censored bound, not a substituted value. The metrics are "
                "therefore conditional on reachability: they say how well an estimator "
                "predicts this attack WHERE THE ATTACK WORKS. Coverage is reported "
                "beside every one of them so the conditioning is never invisible."
            ),
        },
        "arms_agree": _arms_agree(arms),
    }


def _arms_agree(arms: Sequence[Arm]) -> dict[str, Any]:
    """Whether the M3-over-M2 direction on OOV survives every arm.

    A conclusion that appears only under the arm sharing training evidence with
    the PCFG is a statement about shared data. This is the check that says which
    of the two it is, as a table rather than as a sentence.
    """
    summary = {}
    for arm in arms:
        rows = validation_rows(group_rows(arm.rows, "oov_indic"))
        m2 = metrics(rows, "indicpass")
        m3 = metrics(rows, "pcfg")
        summary[arm.name] = {
            "independent_of_estimator_evidence": arm.independent,
            "samples": m2.samples,
            "spearman_indicpass": m2.spearman,
            "spearman_pcfg": m3.spearman,
            "mae_indicpass": m2.mean_absolute_error,
            "mae_pcfg": m3.mean_absolute_error,
            "pcfg_better_spearman": (
                None
                if m2.spearman is None or m3.spearman is None
                else bool(m3.spearman > m2.spearman)
            ),
            "pcfg_better_mae": (
                None
                if m2.samples == 0
                else bool(m3.mean_absolute_error < m2.mean_absolute_error)
            ),
        }
    return summary


def _leakage_statement() -> dict[str, Any]:
    return {
        "candidate_generation_uses_indicpass_scores": False,
        "candidate_generation_uses_pcfg_probabilities": False,
        "candidate_generation_uses_zxcvbn_scores": False,
        "enforced_by": [
            "src/indicpass/password/character_attack.py imports NOTHING but the "
            "standard library -- not the meter, scoring, matcher, baseline or pcfg, "
            "and not even the dictionary.",
            "tests/test_character_attack.py parses that module's imports, asserts the "
            "set is stdlib-only, and fails on any estimator module appearing in it.",
            "tests/test_character_attack.py ranks a corpus with the meter, the PCFG "
            "and the baseline replaced by objects that raise on any attribute access, "
            "and asserts the ranks are unchanged.",
            "tests/test_character_attack.py asserts this script scores the whole "
            "corpus before any attack object is constructed, by parsing the order of "
            "the two calls in main().",
            "The character model is trained on romanized spellings only. No frequency, "
            "no rank, no tier and no estimator output is read anywhere on the path from "
            "the dictionary to a candidate's position.",
        ],
        "partial_independence": (
            "Mechanically complete. Evidentially partial under model=indicdict: the "
            "character model is fitted to the same romanized spellings the PCFG's own "
            "n-gram is fitted to. Different order, different smoothing, different "
            "implementation -- the same data. That arm therefore FAVOURS the PCFG by "
            "construction. The uniform arm shares no evidence with any estimator, and "
            "the report shows both."
        ),
    }


LIMITATIONS: tuple[str, ...] = (
    "The observed rank is a fact about ONE attacker. It is not a real-world cracking "
    "result: this project has no leaked-password corpus, and none is used anywhere.",
    "Under model=indicdict the attack's ordering is trained on the same spellings the "
    "PCFG's n-gram is trained on. A finding that appears only there is partly a "
    "statement about shared evidence. The uniform arm is what separates the two.",
    "The universe admits digits and symbols only as a bounded tail, and a capital only "
    "as the first letter. A password shaped otherwise is unreachable and is reported "
    "with that reason rather than approximated.",
    "Metrics are conditional on reachability. An estimator is scored on the targets "
    "this attack reaches, which is a selected population, and coverage is printed "
    "beside every metric so the selection is visible.",
    "The OOV partition rules are a classification heuristic and will mislabel some "
    "targets. The in_lexicon / oov split itself is exact dictionary membership.",
    "The benchmark is generated, not collected. It is the same 1,400 samples the "
    "earlier milestones used, which makes the numbers comparable and does not make "
    "them representative of real Indian passwords.",
    "The character model is trained on a TYPE distribution -- each spelling once -- so "
    "it models what a Romanized Hindi word looks like, not how often one is written. "
    "An attacker with a password corpus would order candidates better than this.",
    "Quantised levels define this attack's order. They are not probabilities, and the "
    "rank is not an estimate of how many guesses a real attacker would need.",
)

INTERPRETATION_RULES: tuple[str, ...] = (
    "Observed attack rank is a fact about one attacker; estimated guess number is a "
    "model output. They are never the same quantity and are never averaged together.",
    "A positive signed error means the estimator called a password STRONGER than this "
    "attack found it. That is the dangerous direction for a meter.",
    "unreachable != universe_size. An unreachable target carries no rank at all, and "
    "contributes to coverage and to nothing else.",
    "in_lexicon and oov are different populations and their numbers are not comparable "
    "with each other. Every table names which population it is showing.",
    "An interval that excludes zero is reported as excluding zero. It is not a "
    "significance test, and overlapping intervals are not evidence of no difference.",
)


# -- the verdict ------------------------------------------------------------


#: The claim this milestone exists to test, and the two things "useful
#: attack-order information" can mean. They are evaluated by the same rule and
#: reported side by side, because an estimator can win one and lose the other --
#: and collapsing them into a single word would hide exactly that.
CLAIM = (
    "The PCFG's character model provides useful attack-order information for "
    "Romanized Indic passwords whose spelling is absent from IndicDict."
)

#: ``(name, bootstrap statistic, key in _arms_agree, the question it asks)``.
SUB_CLAIMS: tuple[tuple[str, str, str, str], ...] = (
    (
        "ordering",
        "spearman",
        "pcfg_better_spearman",
        "Does M3 order out-of-lexicon targets more like the attack does than M2 "
        "does? The property a strength meter needs, because its job is to tell a "
        "weak password from a strong one.",
    ),
    (
        "calibration",
        "mean_absolute_error",
        "pcfg_better_mae",
        "Does M3 get the NUMBER closer than M2 does? The property a risk "
        "calculation needs. An estimator can be better at this and worse at "
        "ordering, which is why both are decided rather than one.",
    ),
)


def _decide(
    entry: Mapping[str, Any], statistic: str, arms: Mapping[str, Any], key: str
) -> dict[str, Any]:
    """One sub-claim, decided mechanically from the paired interval and the arms."""
    difference = entry["differences"].get(statistic) or {}
    point = difference.get("point")
    low, high = difference.get("ci_low"), difference.get("ci_high")
    higher_is_better = BOOTSTRAP_STATISTICS[statistic]
    favours_pcfg = (
        None if point is None else bool(point > 0.0 if higher_is_better else point < 0.0)
    )
    excludes_zero = bool(low is not None and high is not None and (low > 0.0 or high < 0.0))
    independent = [
        name for name, arm in arms.items() if arm["independent_of_estimator_evidence"]
    ]
    holds_independently = all(arms[name].get(key) for name in independent)

    if point is None:
        status = "untestable"
    elif not favours_pcfg:
        status = "unsupported"
    elif not excludes_zero:
        status = "inconclusive"
    elif holds_independently:
        status = "supported"
    else:
        status = "supported_under_shared_evidence_only"

    return {
        "statistic": statistic,
        "higher_is_better": higher_is_better,
        "status": status,
        "indicpass": entry["indicpass"][statistic],
        "pcfg": entry["pcfg"][statistic],
        "difference": point,
        "difference_ci": [low, high],
        "difference_excludes_zero": excludes_zero,
        "favours_pcfg": favours_pcfg,
        "holds_under_independent_arms": holds_independently,
        "independent_arms": independent,
    }


def verdict(report: Mapping[str, Any]) -> dict[str, Any]:
    """Milestone 3's OOV claim, decided by a rule written before the numbers.

    The rule is deliberately strict and deliberately mechanical, so the answer is
    not a reading of the table. For each of the two sub-claims above:

    * **supported** -- on out-of-lexicon Indic targets the PCFG beats IndicPass,
      the paired interval on the difference excludes zero, and the direction also
      holds under every arm that shares no training evidence with the PCFG.
    * **supported under shared evidence only** -- the same, except that it fails
      under an arm whose ordering the PCFG has no informational advantage in.
    * **inconclusive** -- the PCFG is ahead but the interval includes zero.
    * **unsupported** -- the PCFG is not ahead.
    * **untestable** -- too few reachable out-of-lexicon targets to say.

    The overall status is ``supported`` only if both are, ``partially_supported``
    if exactly one is, and ``unsupported`` if neither. Reporting a split decision
    as a single word in either direction would be the misleading answer.
    """
    entry = next(
        (row for row in report["m2_vs_m3"]["table"] if row["group"] == "oov_indic"), None
    )
    minimum = report["configuration"]["bootstrap"]["min_samples"]
    if entry is None or entry["samples"] < minimum:
        return {
            "claim": CLAIM,
            "status": "untestable",
            "population": "oov_indic",
            "samples": 0 if entry is None else entry["samples"],
            "sub_claims": {},
            "reason": (
                f"{0 if entry is None else entry['samples']} reachable out-of-lexicon "
                f"Indic targets, below the {minimum} this report requires for an "
                "interval."
            ),
        }

    arms = report["controls"]["arms_agree"]
    sub_claims = {
        name: {**_decide(entry, statistic, arms, arm_key), "question": question}
        for name, statistic, arm_key, question in SUB_CLAIMS
    }

    supported = [
        name
        for name, block in sub_claims.items()
        if block["status"] in ("supported", "supported_under_shared_evidence_only")
    ]
    if len(supported) == len(sub_claims):
        status = "supported"
    elif supported:
        status = "partially_supported"
    elif any(block["status"] == "untestable" for block in sub_claims.values()):
        status = "untestable"
    else:
        status = "unsupported"

    return {
        "claim": CLAIM,
        "status": status,
        "population": "oov_indic",
        "samples": entry["samples"],
        "supported_sub_claims": supported,
        "sub_claims": sub_claims,
        "rule": (
            "For each sub-claim: supported = the PCFG beats IndicPass on out-of-lexicon "
            "Indic targets under that statistic, the paired 95% interval on the "
            "difference excludes zero, and the direction also holds under every arm "
            "that shares no training evidence with the PCFG. Overall = supported only "
            "if both sub-claims are, partially_supported if exactly one is. The rule is "
            "fixed here and applied to whatever the numbers turn out to be."
        ),
    }


# -- rendering --------------------------------------------------------------


def _fmt(value: Any, spec: str = ".3f") -> str:
    if value is None:
        return "--"
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return "inf"
    return format(value, spec) if isinstance(value, (int, float)) else str(value)


def _ci(entry: Mapping[str, Any] | None, spec: str = ".3f") -> str:
    if not entry or entry.get("point") is None:
        return "--"
    point = _fmt(entry["point"], spec)
    if entry.get("ci_low") is None:
        return point
    return f"{point} [{_fmt(entry['ci_low'], spec)}, {_fmt(entry['ci_high'], spec)}]"


def render(report: dict[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    attack = report["attack"]
    settings = attack["settings"]

    add(f"# Milestone 5 -- out-of-lexicon attack validation -- {report['language']}")
    add("")
    add(f"Generated {report['generated_at']} from {report['project']} at "
        f"`{report['git_commit'][:12]}`.")
    add("")
    add("Milestone 4 reached 528 of the 1,400 benchmark targets and could not reach the "
        "other 872, because its universe is a wordlist and those passwords are built "
        "from spellings the wordlist lacks. **Milestone 3's central claim is about "
        "exactly those 872.** This report tests it against an attacker whose universe "
        "is every lower-case letter string within a stated length and cost bound, so an "
        "out-of-lexicon spelling is reachable on the same terms as one in the "
        "dictionary.")
    add("")
    add("The rank below is an **observation about one attacker**, not a real-world "
        "cracking result. No leaked password corpus is used anywhere in this project.")
    add("")

    verdict_block = report["verdict"]
    add("## 0. Verdict")
    add("")
    add(f"> **{verdict_block['claim']}**")
    add(">")
    add(f"> Status: **{verdict_block['status'].replace('_', ' ')}**, on "
        f"{verdict_block['samples']} reachable out-of-lexicon Indic targets.")
    add("")
    if verdict_block["sub_claims"]:
        add("| sub-claim | M2 | M3 | paired difference [95% CI] | excludes zero | "
            "holds without shared evidence | status |")
        add("| --- | ---: | ---: | --- | --- | --- | --- |")
        for name, block in verdict_block["sub_claims"].items():
            interval = (
                f"{_fmt(block['difference'])} "
                f"[{_fmt(block['difference_ci'][0])}, {_fmt(block['difference_ci'][1])}]"
                if block["difference_ci"][0] is not None
                else _fmt(block["difference"])
            )
            add(f"| {name} ({block['statistic']}) | {_fmt(block['indicpass'])} | "
                f"{_fmt(block['pcfg'])} | {interval} | "
                f"{block['difference_excludes_zero']} | "
                f"{block['holds_under_independent_arms']} | "
                f"**{block['status'].replace('_', ' ')}** |")
        add("")
        for name, block in verdict_block["sub_claims"].items():
            add(f"* **{name}** -- {block['question']}")
        add("")
    else:
        add(verdict_block.get("reason", ""))
        add("")
    add(f"The rule was fixed before the numbers: {verdict_block['rule']}")
    add("")

    # -- the attack --------------------------------------------------------
    add("## 1. The attack")
    add("")
    add(f"Attack version `{ATTACK_VERSION}`, fingerprint `{attack['fingerprint'][:26]}...`")
    add("")
    add("| dimension | bound |")
    add("| --- | --- |")
    for name, text in attack["search_dimensions"].items():
        add(f"| {name} | {text} |")
    add("")
    add("| setting | value |")
    add("| --- | --- |")
    add(f"| character model | `{settings['model']}`, order {settings['order']}, "
        f"Laplace alpha {settings['smoothing']} |")
    add(f"| trained on | {attack['model']['training_words']:,} romanized spellings "
        f"({attack['model']['training_share']:.0%} of the dictionary) |")
    add(f"| level quantum | {settings['precision']} log10 units |")
    add(f"| budget | 10^{settings['log10_max_candidates']:.0f} candidates -> "
        f"levels 0-{attack['max_level']} |")
    add(f"| budget binds below the table ceiling | {attack['budget_binding']} |")
    add(f"| universe enumerated | {attack['universe_size']:,} = "
        f"10^{attack['log10_universe_size']:.2f} |")
    add(f"| stems counted | 10^{_fmt(attack['stems']['log10_stems_counted'], '.2f')} "
        f"(lengths {settings['min_stem_length']}-{settings['max_stem_length']}) |")
    add(f"| shapes | {len(attack['shapes'])} = {len(report['configuration']['cases'])} cases "
        f"x {report['configuration']['families']} suffix families |")
    add(f"| years / symbols | {settings['year_range'][0]}-{settings['year_range'][1]} / "
        f"{settings['symbol_count']} (`{settings['symbols']}`) |")
    add(f"| model fingerprint | `{attack['model']['fingerprint'][:26]}...` |")
    add("")
    add("Ordering, in full:")
    add("")
    for index, rule in enumerate(attack["ordering"], start=1):
        add(f"{index}. {rule}")
    add("")
    add("Assumptions, in full:")
    add("")
    for item in attack["assumptions"]:
        add(f"* {item}")
    add("")
    add("The first ten shapes, in enumeration order:")
    add("")
    add("| # | shape | level | members |")
    add("| --- | --- | ---: | ---: |")
    for shape in attack["shapes"][:10]:
        add(f"| {shape['index'] + 1} | `{shape['name']}` | {shape['level']} | "
            f"{shape['suffix_size']:,} |")
    add("")

    # -- the partition -----------------------------------------------------
    taxonomy = report["taxonomy"]
    add("## 2. What the 1,400 targets are")
    add("")
    add("The partition is mechanical and is applied before any metric is computed. "
        "Every rule is a membership test against the committed dictionary or the "
        "committed word bank; no target is placed by hand and the benchmark is not "
        "modified.")
    add("")
    for rule in taxonomy["rules"]:
        add(f"* {rule}")
    add("")
    add(f"**Status of these labels.** {taxonomy['status']}")
    add("")
    add("| partition | targets | in IndicDict | reachable | coverage |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for name in PARTITIONS:
        row = taxonomy["partitions"][name]
        add(f"| `{name}` | {row['targets']} | {row['in_lexicon']} | {row['reachable']} | "
            f"{row['coverage']:.1%} |")
    add("")

    # -- coverage ----------------------------------------------------------
    add("## 3. Coverage")
    add("")
    add("An unreachable password is given **no rank** and a named reason. It is never "
        "assigned the universe size, a censored bound, or any substituted value: "
        "`unreachable != universe_size`.")
    add("")
    add("| population | targets | reachable | coverage | median log10 rank | "
        "min | max |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: |")
    for row in report["coverage"]["by_group"]:
        add(f"| `{row['population']}` | {row['targets']} | {row['reachable']} | "
            f"{row['coverage']:.1%} | {_fmt(row['median_log10_rank'], '.2f')} | "
            f"{_fmt(row['min_log10_rank'], '.2f')} | {_fmt(row['max_log10_rank'], '.2f')} |")
    add("")
    add("| benchmark category | targets | reachable | coverage | median log10 rank |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for row in report["coverage"]["by_category"]:
        add(f"| {row['population']} | {row['targets']} | {row['reachable']} | "
            f"{row['coverage']:.1%} | {_fmt(row['median_log10_rank'], '.2f')} |")
    add("")
    reasons = report["coverage"]["overall"]["exclusion_reasons"]
    if reasons:
        add("Why the rest are outside the universe:")
        add("")
        add("| reason | targets |")
        add("| --- | ---: |")
        for reason, count in reasons.items():
            add(f"| `{reason}` | {count} |")
        add("")

    # -- the comparison ----------------------------------------------------
    add("## 4. The estimators against the observed rank")
    add("")
    add("`error = predicted log10 guesses - observed log10 attack rank`. **Positive "
        "means the estimator called the password stronger than this attack found it.** "
        "Every row is computed on reachable targets only, and `n` is that count.")
    add("")
    for group in HEADLINE_GROUPS:
        entries = report["metrics"]["by_group"].get(group, [])
        if not entries or all(entry["samples"] == 0 for entry in entries):
            continue
        add(f"### 4.{HEADLINE_GROUPS.index(group) + 1} `{group}`")
        add("")
        add("| estimator | n | Spearman | Pearson | mean err | MAE | RMSE | +-1.0 | "
            "direction |")
        add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |")
        for entry in entries:
            add(f"| {entry['label']} | {entry['samples']} | {_fmt(entry['spearman'])} | "
                f"{_fmt(entry['pearson'])} | {entry['mean_signed_error']:+.3f} | "
                f"{entry['mean_absolute_error']:.3f} | {entry['rmse']:.3f} | "
                f"{entry['within_1.0_log10']:.1%} | {entry['direction']} |")
        add("")
        winners = report["metrics"]["winners"].get(group, {})
        best = ", ".join(
            f"{metric}: {value['label']} ({_fmt(value['value'])})"
            for metric, value in winners.items()
            if value
        )
        add(f"Winner by metric -- {best}")
        add("")

    add("### 4.5 Every partition")
    add("")
    add("Populations are **not** comparable with each other; each row is conditional on "
        "its own coverage.")
    add("")
    add("| population | estimator | n | Spearman | mean err | MAE | +-1.0 |")
    add("| --- | --- | ---: | ---: | ---: | ---: | ---: |")
    for group in PARTITIONS:
        for entry in report["metrics"]["by_group"].get(group, []):
            if entry["estimator"] not in PRIMARY_ESTIMATORS or entry["samples"] == 0:
                continue
            first = entry["estimator"] == PRIMARY_ESTIMATORS[0]
            add(f"| {'`' + group + '`' if first else ''} | {entry['label']} | "
                f"{entry['samples']} | {_fmt(entry['spearman'])} | "
                f"{entry['mean_signed_error']:+.3f} | {entry['mean_absolute_error']:.3f} | "
                f"{entry['within_1.0_log10']:.1%} |")
    add("")

    # -- M2 vs M3 ----------------------------------------------------------
    add("## 5. The question: M3 against M2, on out-of-lexicon targets")
    add("")
    add(report["m2_vs_m3"]["note"])
    add("")
    add("| population | n | rho M2 | rho M3 | rho difference [95% CI] | MAE M2 | MAE M3 | "
        "MAE difference [95% CI] |")
    add("| --- | ---: | ---: | ---: | --- | ---: | ---: | --- |")
    for row in report["m2_vs_m3"]["table"]:
        add(f"| `{row['group']}` | {row['samples']} | "
            f"{_fmt(row['indicpass']['spearman'])} | {_fmt(row['pcfg']['spearman'])} | "
            f"{_ci(row['differences'].get('spearman'))} | "
            f"{row['indicpass']['mean_absolute_error']:.2f} | "
            f"{row['pcfg']['mean_absolute_error']:.2f} | "
            f"{_ci(row['differences'].get('mean_absolute_error'), '.2f')} |")
    add("")

    # -- uncertainty -------------------------------------------------------
    add("## 6. Confidence intervals")
    add("")
    bootstrap = report["uncertainty"]
    first_group = next(iter(bootstrap.values()), {})
    add(f"Percentile bootstrap, {first_group.get('resamples', 0)} resamples, "
        f"seed {report['configuration']['bootstrap']['seed']}, "
        f"{first_group.get('confidence', 0.95):.0%} interval. Resample indices are drawn "
        "once per population and shared by every estimator, so the differences in "
        "section 5 are paired. **An interval that excludes zero is reported as "
        "excluding zero; it is not called significant.**")
    add("")
    for group in HEADLINE_GROUPS:
        block = bootstrap.get(group)
        if not block:
            continue
        add(f"**`{group}`** -- n = {block['samples']}"
            + (", point estimates only (below the minimum)" if block["below_minimum"] else ""))
        add("")
        add("| estimator | Spearman | MAE | RMSE | +-1.0 | calibration slope | r^2 |")
        add("| --- | --- | --- | --- | --- | --- | --- |")
        for name in PRIMARY_ESTIMATORS:
            entry = block["estimators"].get(name)
            if not entry:
                continue
            add(f"| {ESTIMATOR_LABELS[name]} | {_ci(entry['spearman'])} | "
                f"{_ci(entry['mean_absolute_error'], '.2f')} | "
                f"{_ci(entry['rmse'], '.2f')} | "
                f"{_ci(entry['within_1.0_log10'])} | "
                f"{_ci(entry['calibration_slope'])} | {_ci(entry['r_squared'])} |")
        add("")

    # -- arms --------------------------------------------------------------
    add("## 7. Does the answer depend on the attacker?")
    add("")
    add("Each arm is the attack above with exactly one thing changed. The `indicdict` "
        "arm shares its training evidence with the PCFG's n-gram; `uniform` shares "
        "none. **A conclusion is only safe where the arms agree.**")
    add("")
    add("| arm | shares evidence | log10 universe | coverage all / oov_indic | "
        "rho M2 / M3 (oov_indic) |")
    add("| --- | --- | ---: | ---: | --- |")
    for arm in report["arms"]:
        by_name = {entry["estimator"]: entry for entry in arm["metrics"].get("oov_indic", [])}
        rho = " / ".join(
            _fmt(by_name.get(name, {}).get("spearman"), ".3f")
            for name in ("indicpass", "pcfg")
        )
        add(f"| `{arm['name']}` | "
            f"{'NO' if arm['independent_of_estimator_evidence'] else 'yes'} | "
            f"{_fmt(arm['attack'].get('log10_universe_size'), '.2f')} | "
            f"{arm['coverage']['all']['coverage']:.1%} / "
            f"{arm['coverage']['oov_indic']['coverage']:.1%} | {rho} |")
    add("")
    for arm in report["arms"]:
        add(f"* **`{arm['name']}`** -- {arm['description']}")
    add("")

    # -- controls ----------------------------------------------------------
    controls = report["controls"]
    add("## 8. Controls")
    add("")
    separation = controls["separation"]
    add("### 8.1 Does the model carry information, or is it matching noise?")
    add("")
    add(f"Median log10 rank: **{_fmt(separation['median_log10_rank_in_lexicon'], '.2f')}** "
        f"in-lexicon, **{_fmt(separation['median_log10_rank_oov_indic'], '.2f')}** "
        f"out-of-lexicon Indic, **{_fmt(separation['median_log10_rank_random'], '.2f')}** "
        f"random controls -- a separation of "
        f"**{_fmt(separation['orders_of_magnitude_separation'], '.2f')} orders of "
        f"magnitude** between out-of-lexicon Hindi and noise.")
    add("")
    add(separation["note"])
    add("")

    leakage = controls["leakage"]
    add("### 8.2 Leakage and independence")
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

    add("### 8.3 Does the direction survive every arm?")
    add("")
    add("| arm | shares evidence | n | rho M2 | rho M3 | M3 wins rho | M3 wins MAE |")
    add("| --- | --- | ---: | ---: | ---: | --- | --- |")
    for name, row in controls["arms_agree"].items():
        add(f"| `{name}` | "
            f"{'NO' if row['independent_of_estimator_evidence'] else 'yes'} | "
            f"{row['samples']} | {_fmt(row['spearman_indicpass'])} | "
            f"{_fmt(row['spearman_pcfg'])} | {row['pcfg_better_spearman']} | "
            f"{row['pcfg_better_mae']} |")
    add("")

    selection = controls["selection"]
    add("### 8.4 Selection")
    add("")
    add(f"{selection['reachable']} reachable, {selection['unreachable']} unreachable. "
        f"{selection['note']}")
    add("")

    # -- reproducibility ---------------------------------------------------
    repro = report["reproducibility"]
    add("## 9. Reproducibility")
    add("")
    add("| quantity | value |")
    add("| --- | --- |")
    add(f"| canonical report SHA-256 | `{repro['canonical_sha256']}` |")
    add(f"| second process run | {repro['second_process_run']} |")
    add(f"| byte-identical across processes | {repro['byte_identical']} |")
    add(f"| attack fingerprint | `{attack['fingerprint']}` |")
    add(f"| character model fingerprint | `{attack['model']['fingerprint']}` |")
    add(f"| benchmark corpus digest | `{report['corpus_digest']}` |")
    for name, value in report["artifact_hashes"].items():
        add(f"| {name} | `{value}` |")
    add("")
    add(repro["note"])
    add("")
    add("Exact reproduction command:")
    add("")
    add("```bash")
    add(report["reproduction"]["command"])
    add("```")
    add("")

    # -- limitations -------------------------------------------------------
    add("## 10. Limitations")
    add("")
    for item in report["limitations"]:
        add(f"* {item}")
    add("")
    add("## 11. How to read this")
    add("")
    for item in report["interpretation_rules"]:
        add(f"* {item}")
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
    print("MILESTONE 5 -- out-of-lexicon attack validation")
    print(f"{'=' * width}")
    print(f"  attack        {len(attack['shapes'])} shapes, levels 0-{attack['max_level']}, "
          f"universe 10^{attack['log10_universe_size']:.2f} "
          f"({attack['settings']['model']}, order {attack['settings']['order']})")
    total = report["coverage"]["overall"]
    print(f"  coverage      {total['reachable']}/{total['targets']} "
          f"({total['coverage']:.1%})")
    print()
    print(f"  {'population':<22}{'n':>6}{'rho M2':>10}{'rho M3':>10}"
          f"{'MAE M2':>10}{'MAE M3':>10}")
    for row in report["m2_vs_m3"]["table"]:
        if row["group"] not in HEADLINE_GROUPS:
            continue
        print(f"  {row['group']:<22}{row['samples']:>6}"
              f"{_fmt(row['indicpass']['spearman']):>10}"
              f"{_fmt(row['pcfg']['spearman']):>10}"
              f"{row['indicpass']['mean_absolute_error']:>10.3f}"
              f"{row['pcfg']['mean_absolute_error']:>10.3f}")
    print()
    separation = report["controls"]["separation"]
    print(f"  separation    in-lexicon {_fmt(separation['median_log10_rank_in_lexicon'], '.2f')}"
          f" | oov {_fmt(separation['median_log10_rank_oov_indic'], '.2f')}"
          f" | random {_fmt(separation['median_log10_rank_random'], '.2f')}"
          f"  (delta {_fmt(separation['orders_of_magnitude_separation'], '.2f')})")
    print()
    print(f"  {'arm':<16}{'indep':>7}{'cover':>8}   rho M2 / M3 on oov_indic")
    for name, row in report["controls"]["arms_agree"].items():
        arm = next(entry for entry in report["arms"] if entry["name"] == name)
        print(f"  {name:<16}"
              f"{'yes' if row['independent_of_estimator_evidence'] else 'NO':>7}"
              f"{arm['coverage']['oov_indic']['coverage']:>8.1%}   "
              f"{_fmt(row['spearman_indicpass'])} / {_fmt(row['spearman_pcfg'])}")
    print()
    block = report["verdict"]
    print(f"  VERDICT       {block['status'].upper().replace('_', ' ')} "
          f"on {block['samples']} oov_indic targets")
    for name, sub in block["sub_claims"].items():
        low, high = sub["difference_ci"]
        print(f"    {name:<13}{sub['statistic']:<22}"
              f"M3-M2 {_fmt(sub['difference']):>7} "
              f"[{_fmt(low):>6}, {_fmt(high):>6}]  {sub['status']}")
    repro = report["reproducibility"]
    print(f"  reproducible  sha {repro['canonical_sha256'][:24]}... "
          f"byte-identical={repro['byte_identical']}")
    print()


# -- main -------------------------------------------------------------------


def canonical_payload(report: Mapping[str, Any]) -> bytes:
    """The report with the volatile keys removed, serialised deterministically.

    This is what two processes must agree on byte for byte. ``generated_at``
    differs by construction, and the reproducibility block cannot contain its own
    comparison, so both are excluded and nothing else is.
    """
    stripped = {key: value for key, value in report.items() if key not in VOLATILE_KEYS}
    return (
        json.dumps(stripped, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def _settings(section: Mapping[str, Any], overrides: Mapping[str, Any]) -> CharacterAttackSettings:
    return dataclasses.replace(CharacterAttackSettings.from_config(section), **dict(overrides))


def _model_for(
    words: Sequence[str], settings: CharacterAttackSettings, cache: dict[tuple, CharacterModel]
) -> CharacterModel:
    key = (
        settings.model,
        settings.order,
        settings.smoothing,
        settings.precision,
        settings.training_share,
        settings.training_seed,
    )
    model = cache.get(key)
    if model is None:
        model = cache[key] = CharacterModel.train(
            words,
            order=settings.order,
            smoothing=settings.smoothing,
            precision=settings.precision,
            kind=settings.model,
            share=settings.training_share,
            seed=settings.training_seed,
        )
    return model


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("The character attack is built from one dictionary. Pass --languages hin.")
        return 2
    language = languages[0]

    section = config.password_section("character_attack")
    evaluation = config.password_section("evaluation")
    attack_evaluation = dict(section.get("evaluation") or {})
    bootstrap_config = dict(section.get("bootstrap") or {})
    resamples = args.resamples if args.resamples is not None else int(
        bootstrap_config.get("resamples", 2000)
    )
    bootstrap_settings = {
        "resamples": resamples,
        "seed": int(bootstrap_config.get("seed", 42)),
        "confidence": float(bootstrap_config.get("confidence", 0.95)),
        "min_samples": int(bootstrap_config.get("min_samples", 20)),
    }

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
            "No PCFG loaded. This milestone exists to test the PCFG's out-of-lexicon "
            "claim; without one there is nothing to test. Train it with "
            "scripts/train_pcfg.py --languages hin."
        )
        return 2

    samples = generate_corpus(seed=seed, samples_per_category=per_category)
    logger.info("Corpus: %d samples across %d categories", len(samples), len(CATEGORIES))

    # Scored FIRST, before any attack object exists. See the module docstring,
    # and tests/test_character_attack.py, which asserts this ordering by parsing
    # this function.
    started = time.perf_counter()
    predictions = score_predictions(meter, samples)
    logger.info(
        "Scored %d samples with three estimators in %.1fs",
        len(predictions),
        time.perf_counter() - started,
    )

    words = dictionary_stem_corpus(dictionary)
    taxonomy = Taxonomy(words)
    logger.info("Training corpus: %d lower-case spellings", len(words))

    arms = [dataclasses.replace(arm, rows=[], attack=None) for arm in ARMS]
    if args.no_arms:
        arms = arms[:1]

    cache: dict[tuple, CharacterModel] = {}
    for arm in arms:
        started = time.perf_counter()
        settings = _settings(section, arm.overrides)
        attack = CharacterAttack.build(_model_for(words, settings, cache), settings)
        arm.attack = attack
        arm.rows = build_rows(attack, samples, taxonomy, predictions)
        reached = sum(1 for row in arm.rows if row.reachable)
        logger.info(
            "%-16s levels 0-%d, universe 10^%.2f, reached %d/%d in %.1fs",
            arm.name,
            attack.max_level,
            math.log10(attack.universe_size),
            reached,
            len(arm.rows),
            time.perf_counter() - started,
        )

    primary = arms[0]
    assert primary.attack is not None
    columns = available_columns(primary.rows)

    started = time.perf_counter()
    bootstrap: dict[str, Any] = {}
    for group in REPORT_GROUPS:
        selected = [
            row
            for row in group_rows(primary.rows, group)
            if row.reachable and row.log10_rank is not None
        ]
        bootstrap[group] = bootstrap_group(
            [float(row.log10_rank) for row in selected],  # type: ignore[arg-type]
            {
                name: [row.predictions[name] for row in selected]
                for name in PRIMARY_ESTIMATORS
                if name in columns
            },
            pairs=ESTIMATOR_PAIRS,
            seed=bootstrap_settings["seed"],
            resamples=resamples,
            confidence=bootstrap_settings["confidence"],
            min_samples=bootstrap_settings["min_samples"],
            label=group,
        )
    logger.info(
        "Bootstrapped %d populations x %d resamples in %.1fs",
        len(REPORT_GROUPS),
        resamples,
        time.perf_counter() - started,
    )

    command = (
        f"python scripts/milestone5_oov_attack.py --languages {language.code} "
        f"--samples {per_category} --seed {seed} --resamples {resamples}"
    )
    header = {
        "report": SCRIPT,
        "attack_version": ATTACK_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(config.root),
        "project": f"{config.name} v{config.version}",
        "language": language.code,
        "corpus_seed": seed,
        "corpus": {**describe_corpus(samples), "generator_version": GENERATOR_VERSION},
        "corpus_digest": corpus_digest(samples),
        "dictionaries": describe_dictionaries(meter),
        "pcfg": describe_pcfg(meter),
        "baseline_name": meter.baseline.name,
        "estimator_columns": {name: ESTIMATOR_LABELS[name] for name in columns},
        "artifact_hashes": {
            "dictionary_file": file_digest(path),
            "pcfg_artefact": file_digest(
                config.resolve((config.password_section("pcfg").get("files") or {})[language.code])
            ),
            "attack_fingerprint": primary.attack.fingerprint(),
            "character_model_fingerprint": primary.attack.model.fingerprint(),
        },
        "configuration": {
            "settings": primary.attack.settings.to_dict(),
            "bootstrap": bootstrap_settings,
            "arms": [arm.name for arm in arms],
            "cases": ["lower", "capitalized", "upper"],
            "families": len(primary.attack.shapes) // 3,
            "groups": list(REPORT_GROUPS),
        },
    }

    report = build_report(
        header=header, arms=arms, bootstrap=bootstrap, reproduction_command=command
    )
    report["verdict"] = verdict(report)

    payload = canonical_payload(report)
    digest = hashlib.sha256(payload).hexdigest()

    if args.canonical_out is not None:
        args.canonical_out.parent.mkdir(parents=True, exist_ok=True)
        args.canonical_out.write_bytes(payload)
        logger.info("Canonical payload written to %s (sha256:%s)", args.canonical_out, digest)
        return 0

    identical: bool | None = None
    child_digest: str | None = None
    if not args.no_repro_check:
        logger.info("Re-running the experiment in a second process to check byte identity")
        scratch = config.ensure_dir("reports") / f".{SCRIPT}_repro.json"
        child = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--languages", language.code,
                "--samples", str(per_category),
                "--seed", str(seed),
                "--resamples", str(resamples),
                "--canonical-out", str(scratch),
                "--no-repro-check",
                "--log-level", "ERROR",
            ],
            cwd=config.root,
            capture_output=True,
            text=True,
        )
        if child.returncode != 0:
            logger.error("The second process failed: %s", child.stderr.strip()[-2000:])
        else:
            other = scratch.read_bytes()
            identical = other == payload
            child_digest = hashlib.sha256(other).hexdigest()
            scratch.unlink(missing_ok=True)
            logger.info("Second process: byte-identical=%s", identical)

    report["reproducibility"] = {
        "canonical_sha256": f"sha256:{digest}",
        "second_process_sha256": None if child_digest is None else f"sha256:{child_digest}",
        "second_process_run": not args.no_repro_check,
        "byte_identical": identical,
        "excluded_from_hash": sorted(VOLATILE_KEYS),
        "note": (
            "The canonical payload is this report with generated_at and this block "
            "removed, serialised with sorted keys. The experiment was run a second time "
            "in a SEPARATE PROCESS from the same configuration and seed, and the two "
            "payloads were compared byte for byte -- not merely re-derived inside one "
            "interpreter, where a shared cache could hide a dependence on run order."
        ),
    }

    print_console(report)

    if args.no_report:
        return 0

    directory = (
        config.resolve(args.report_dir) if args.report_dir else config.ensure_dir("reports")
    )
    directory.mkdir(parents=True, exist_ok=True)
    prefix = attack_evaluation.get("report_prefix", SCRIPT)
    base = directory / prefix
    base.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render(report), encoding="utf-8")
    logger.info("Report written to %s", config.relative(base.with_suffix(".md")))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
