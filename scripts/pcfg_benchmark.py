#!/usr/bin/env python
"""Evaluate the Indic PCFG against zxcvbn and against the Milestone 2 estimator.

    python scripts/pcfg_benchmark.py --languages hin
    python scripts/pcfg_benchmark.py --languages hin --samples 40 --no-report  # smoke run

Same corpus, same seed, same categories as Milestone 2 -- 1,400 generated
samples from ``evaluation.seed`` -- so the two milestones' numbers sit in the
same table without either being re-derived.

Three estimators score every password in the same call: the Milestone 2 meter,
the PCFG, and zxcvbn. Nothing is compared across runs.

What is being asked
-------------------
Not "is the PCFG better". A guess estimate is only *better* against a reference
attack, and this project has none. What can be asked is whether a probability
model over Romanized-Indic password structure carries information the generic
estimator lacks -- measured as ``min(PCFG, zxcvbn)`` against zxcvbn alone -- and
whether it does so **without** inventing structure in strings that have none,
which the random controls decide.

Two reports come out of one scoring pass, because they share a corpus and would
be incomparable otherwise:

``pcfg_benchmark_<lang>``
    The per-category comparison, the derivation census, the random control
    summary, and every design-decision ablation.
``pcfg_targeted_<lang>``
    The hand-chosen cases one at a time, and the full random-control sweep.

No password is written to either. Rows are keyed on ``sample_id`` or on
``case_id``, and both corpora regenerate from committed source.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import time
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config
from indicpass.password.baseline import BaselineUnavailable, load_baseline
from indicpass.password.benchmark import (
    CATEGORIES,
    GENERATOR_VERSION,
    BenchmarkSample,
    describe_corpus,
    generate_corpus,
)
from indicpass.password.dictionary import IndicDict
from indicpass.password.experiment import (
    SampleResult,
    aggregate,
    compare_estimators_all,
    pcfg_structure_census,
    score_corpus,
    shadow_rows,
)
from indicpass.password.matcher import MatcherSettings
from indicpass.password.meter import IndicPassMeter, describe_dictionaries
from indicpass.password.pcfg.artifact import dictionary_fingerprint
from indicpass.password.pcfg.estimator import EstimatorSettings, PcfgEstimator
from indicpass.password.pcfg.grammar import GrammarSettings, PcfgGrammar
from indicpass.password.pcfg.probe import (
    character_model_fit,
    random_control_probe,
    score_targeted_cases,
)
from indicpass.password.scoring import ScoringSettings, StrengthScale

SCRIPT = "pcfg_benchmark"

INDIC_CATEGORIES = ("indic_word", "indic_numeric", "indic_year", "indic_symbol")
CONTROL_CATEGORIES = ("english", "random")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pcfg_benchmark.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--samples", type=int, metavar="N", help="Samples per category.")
    parser.add_argument("--seed", type=int, metavar="N", help="Corpus seed.")
    parser.add_argument("--dictionary", type=Path, metavar="FILE", help="Dictionary to use.")
    parser.add_argument("--report-dir", type=Path, metavar="DIR", help="Where the reports land.")
    parser.add_argument(
        "--curve-samples",
        type=int,
        metavar="N",
        help="Derivations per ablation arm's guess curve. Default from config.",
    )
    parser.add_argument(
        "--control-samples", type=int, metavar="N", help="Random strings per control cell."
    )
    parser.add_argument("--no-ablations", action="store_true", help="Skip the ablation arms.")
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


# -- arms ------------------------------------------------------------------


@dataclasses.dataclass
class Arm:
    """One configuration of the PCFG, and the question it answers."""

    name: str
    description: str
    grammar: dict[str, Any] = dataclasses.field(default_factory=dict)
    estimator: dict[str, Any] = dataclasses.field(default_factory=dict)
    results: list[SampleResult] = dataclasses.field(default_factory=list)


#: Every arm is the shipped configuration with exactly one thing changed. The
#: first four exist because those choices are *assumptions* -- the structure
#: prior is not learned from anything -- and an assumption that moves the
#: conclusion has to be measured rather than defended.
ABLATION_ARMS: tuple[Arm, ...] = (
    Arm(
        "no_bruteforce_floor",
        "The grammar's own number, with min(grammar, brute force) turned off. "
        "Isolates what the retained non-PCFG floor is doing -- on the random "
        "controls, everything.",
        estimator={"bruteforce_floor": False},
    ),
    Arm(
        "no_character_model",
        "The `unknown` category removed, so only dictionary words, digits, years "
        "and symbols can derive a span. This is the PCFG WITHOUT the character "
        "n-gram: it isolates the component added to address Milestone 2's "
        "coverage ceiling.",
        grammar={
            "category_prior": {"word": 1.0, "digits": 1.0, "year": 1.0, "symbols": 1.0}
        },
    ),
    Arm(
        "no_dictionary",
        "The `word` category removed. Everything alphabetic must go through the "
        "character model. Isolates the lexicon from the shape model -- the two "
        "halves of the Indic claim.",
        grammar={
            "category_prior": {"unknown": 1.0, "digits": 1.0, "year": 1.0, "symbols": 1.0}
        },
    ),
    Arm(
        "segments_0.3",
        "Structure prior with q=0.3 instead of 0.5: multi-segment passwords are "
        "assumed rarer. An ASSUMPTION arm -- no data chose 0.5 either.",
        grammar={"segment_continuation": 0.3},
    ),
    Arm(
        "segments_0.7",
        "Structure prior with q=0.7: multi-segment passwords assumed commoner. "
        "The other side of the same assumption.",
        grammar={"segment_continuation": 0.7},
    ),
    Arm(
        "category_lexical",
        "Category prior skewed towards lexical segments (word 0.40, unknown 0.30, "
        "digits 0.15, symbols 0.10, year 0.05) instead of uniform. Plausible, and "
        "measured by nothing -- which is exactly why it is an arm and not the "
        "default. It bounds what the maximum-entropy choice costs.",
        grammar={
            "category_prior": {
                "word": 0.40, "unknown": 0.30, "digits": 0.15,
                "symbols": 0.10, "year": 0.05,
            }
        },
    ),
    Arm(
        "curve_seed_7",
        "The same grammar with the guess curve re-sampled from a different seed. "
        "Not a design choice: this bounds the Monte-Carlo estimator's own variance, "
        "so a reader can tell a real effect from sampling noise.",
        estimator={"sample_seed": 7},
    ),
    Arm(
        "ngram_order_3",
        "A shorter character model. Less context, more backoff.",
        grammar={"ngram_order": 3},
    ),
    Arm(
        "ngram_order_5",
        "A longer character model. More context, sparser counts.",
        grammar={"ngram_order": 5},
    ),
    Arm(
        "ngram_curated_only",
        "The character model trained without the 120,000-entry mined tier, which "
        "is the least precise source and the one Milestone 2 had to clear of "
        "carrying its result.",
        grammar={"ngram_tiers": ["human_romanized", "curated_entities", "curated_other"]},
    ),
    Arm(
        "unranked_uniform",
        "Entries with no observed frequency weighted alike across tiers instead "
        "of by their tier's measured coverage.",
        grammar={"unranked_policy": "uniform"},
    ),
    Arm(
        "unranked_excluded",
        "Entries with no observed frequency dropped from the word category "
        "entirely -- 86% of the dictionary -- leaving the character model to "
        "explain them.",
        grammar={"unranked_policy": "excluded"},
    ),
)


def build_arm(
    arm: Arm,
    *,
    dictionary: IndicDict,
    grammar_settings: GrammarSettings,
    estimator_settings: EstimatorSettings,
    scale: StrengthScale,
) -> PcfgEstimator:
    """Fit one arm from scratch: grammar and guess curve both.

    Re-sampling the curve is not optional. The curve is the distribution of
    probabilities the grammar produces, so an arm that changed the grammar and
    kept the old curve would map its probabilities through a model of a
    different grammar -- every number in that arm would be wrong in a way no
    reader could see.
    """
    grammar = PcfgGrammar.train(
        dictionary, dataclasses.replace(grammar_settings, **_grammar_overrides(arm.grammar))
    )
    return PcfgEstimator.train(
        grammar,
        settings=dataclasses.replace(estimator_settings, **arm.estimator),
        scale=scale,
    )


def _grammar_overrides(raw: dict[str, Any]) -> dict[str, Any]:
    overrides = dict(raw)
    if "ngram_tiers" in overrides:
        overrides["ngram_tiers"] = tuple(overrides["ngram_tiers"])
    return overrides


# -- report assembly -------------------------------------------------------


def _header(
    config: Config,
    *,
    dictionary_info: Any,
    corpus: Sequence[BenchmarkSample],
    baseline: Any,
    estimator: PcfgEstimator,
    dictionary: IndicDict,
    seed: int,
) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": f"{config.name} v{config.version}",
        "git_commit": git_commit(config.root),
        "milestone": 3,
        "corpus": {"seed": seed, **describe_corpus(corpus)},
        "baseline": baseline.describe(),
        "dictionaries": dictionary_info,
        "pcfg": estimator.describe(),
        "dictionary_fingerprint": dictionary_fingerprint(dictionary),
    }


def _stats_by_category(results: Sequence[SampleResult], estimator: str) -> dict[str, Any]:
    present = [name for name in CATEGORIES if any(r.category == name for r in results)]
    out = {}
    for name in present:
        rows = [r for r in results if r.category == name]
        out[name] = aggregate(shadow_rows(rows, estimator), name).to_dict()
    return out


def build_benchmark_report(
    *,
    header: dict[str, Any],
    results: Sequence[SampleResult],
    arms: Sequence[Arm],
    control: dict[str, Any],
    character_model: dict[str, Any],
) -> dict[str, Any]:
    comparisons = compare_estimators_all(results, left="pcfg", right="baseline")
    against_meter = compare_estimators_all(results, left="pcfg", right="indicpass")

    present = [name for name in CATEGORIES if any(r.category == name for r in results)]
    three_way = {
        estimator: _stats_by_category(results, estimator)
        for estimator in ("indicpass", "pcfg", "baseline")
    }

    # min over every estimator that ran. An attacker holds all of them.
    triple: dict[str, dict[str, float]] = {}
    for name in present:
        rows = [r for r in results if r.category == name]
        values = [
            min(r.log10_guesses, r.pcfg_log10_guesses or r.log10_guesses,
                r.baseline_log10_guesses or r.log10_guesses)
            for r in rows
        ]
        base = [r.baseline_log10_guesses or 0.0 for r in rows]
        triple[name] = {
            "mean_log10_guesses": round(sum(values) / len(values), 4),
            "mean_information_added": round(
                sum(v - b for v, b in zip(values, base, strict=True)) / len(values), 4
            ),
            "samples_improved": sum(1 for v, b in zip(values, base, strict=True) if v < b - 0.05),
            "samples": len(rows),
        }

    return {
        **header,
        "question": (
            "Does a probabilistic grammar over Romanized-Indic password structure carry "
            "information a generic estimator lacks, without inventing structure in "
            "strings that have none?"
        ),
        "hypothesis_categories": list(INDIC_CATEGORIES),
        "control_categories": list(CONTROL_CATEGORIES),
        "pcfg_vs_baseline": [c.to_dict() for c in comparisons],
        "pcfg_vs_indicpass": [c.to_dict() for c in against_meter],
        "by_estimator": three_way,
        "combined_all_three": triple,
        "structures": [pcfg_structure_census(results, name) for name in present],
        "character_model": character_model,
        "random_control": control,
        "ablations": [
            {
                "name": arm.name,
                "description": arm.description,
                "grammar_overrides": arm.grammar,
                "estimator_overrides": arm.estimator,
                "by_category": _stats_by_category(arm.results, "pcfg"),
                "delta_vs_shipped": {
                    name: round(
                        aggregate_pcfg(arm.results, name) - aggregate_pcfg(results, name), 4
                    )
                    for name in present
                },
            }
            for arm in arms
        ],
        "samples": [row.to_dict() for row in results],
        "interpretation_note": (
            "A lower estimate is NOT automatically a more accurate one. Establishing "
            "that needs a reference attack -- a cracking run against a real leak -- "
            "which this project does not have. These numbers state the direction and "
            "the magnitude and stop there."
        ),
    }


def aggregate_pcfg(results: Sequence[SampleResult], category: str) -> float:
    rows = [r.pcfg_log10_guesses for r in results if r.category == category]
    values = [v for v in rows if v is not None]
    return sum(values) / len(values) if values else 0.0


def build_targeted_report(
    *, header: dict[str, Any], cases: Sequence[dict[str, Any]], control: dict[str, Any]
) -> dict[str, Any]:
    return {
        **header,
        "question": (
            "What does the grammar actually derive, one case at a time, and does it "
            "invent lexical structure in random strings?"
        ),
        "cases": list(cases),
        "families": sorted({row["family"] for row in cases}),
        "random_control": control,
        "redaction_note": (
            "Rows are keyed on case_id. The probe passwords are committed source in "
            "src/indicpass/password/pcfg/probe.py, where the whole instrument can be "
            "read at once; what is forbidden -- and what this report does not do -- is "
            "publish a table pairing an identifier with a password."
        ),
    }


# -- markdown --------------------------------------------------------------


def _header_lines(report: dict[str, Any], title: str) -> list[str]:
    corpus = report["corpus"]
    entry = (report["dictionaries"] or [{}])[0]
    source = (entry.get("frequency_source") or {}).get("identifier", "none")
    pcfg = report["pcfg"]
    grammar = pcfg["grammar"]["settings"]
    return [
        f"# {title}",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Git commit:** `{report['git_commit']}`",
        f"- **Baseline:** {report['baseline']['name']} {report['baseline']['version']}",
        f"- **Dictionary:** {entry.get('entries', 0):,} entries, "
        f"{entry.get('ranked_entries', 0):,} with an observed frequency "
        f"({entry.get('frequency_coverage', 0) * 100:.1f}%)",
        f"- **Frequency source:** `{source}`",
        f"- **Grammar:** order-{grammar['ngram_order']} character model, "
        f"geometric(q={grammar['segment_continuation']}) segment prior truncated at "
        f"{grammar['max_segments']}, "
        f"{'uniform' if not grammar['category_prior'] else 'configured'} category prior",
        f"- **Guess curve:** {pcfg['curve']['samples']:,} sampled derivations, seed "
        f"{pcfg['curve']['seed']}, {pcfg['curve']['points']} stored points",
        f"- **Dictionary fingerprint:** `{report['dictionary_fingerprint'][:23]}...`",
        f"- **Corpus:** {corpus['total_samples']:,} generated samples, seed "
        f"{corpus['seed']}, generator {corpus['generator_version']}",
        "",
        "Rows are keyed on `sample_id`. **No row maps an id to a password**, and no",
        "composed password -- word plus digits, symbol, year, or any random string --",
        "is written anywhere. The corpus regenerates exactly from the seed above.",
        "",
        "> **The PCFG is a model, not a measurement of attacker behaviour.** Nothing",
        "> here has been validated against an observed cracking run. \"Estimates fewer",
        "> guesses\" is a statement about two models, not about reality.",
        "",
    ]


def _margin(fit: dict[str, Any]) -> float:
    """How far the character model beats the floor, per character of unseen Hindi.

    Positive means the model is cheaper than enumerating. Only this margin can
    ever reach a reported estimate -- the model's discrimination between Hindi
    and noise is much larger, and mostly invisible because of it.
    """
    absent = fit["populations"]["indic_bank_absent_from_dictionary"]
    return fit["bruteforce_floor_cost_per_character"] - absent["log10_cost_per_character"]


def render_benchmark(report: dict[str, Any]) -> str:
    lines = _header_lines(report, "PCFG benchmark -- IndicPass PCFG vs zxcvbn")
    lines += [
        "## The question",
        "",
        f"> {report['question']}",
        "",
        f"Hypothesis categories: {', '.join(f'`{c}`' for c in report['hypothesis_categories'])}. "
        f"Controls: {', '.join(f'`{c}`' for c in report['control_categories'])}.",
        "",
        "## Three estimators, same passwords, same call",
        "",
        "| Category | N | Milestone 2 median | **PCFG median** | zxcvbn median |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    by_estimator = report["by_estimator"]
    for name, row in by_estimator["pcfg"].items():
        lines.append(
            f"| {name} | {row['samples']} "
            f"| {by_estimator['indicpass'][name]['median_log10_guesses']:.2f} "
            f"| **{row['median_log10_guesses']:.2f}** "
            f"| {by_estimator['baseline'][name]['median_log10_guesses']:.2f} |"
        )

    lines += [
        "",
        "## PCFG against zxcvbn",
        "",
        "`Difference` is mean log10(PCFG) - mean log10(zxcvbn). **Negative means the",
        "PCFG estimates fewer guesses.**",
        "",
        "| Category | N | PCFG mean | zxcvbn mean | Mean diff | Median diff "
        "| PCFG lower | PCFG higher | equal |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["pcfg_vs_baseline"]:
        lines.append(
            f"| {row['category']} | {row['samples']} "
            f"| {row['pcfg_stats']['mean_log10_guesses']:.2f} "
            f"| {row['baseline_stats']['mean_log10_guesses']:.2f} "
            f"| {row['mean_log10_difference']:+.2f} "
            f"| {row['median_log10_difference']:+.2f} "
            f"| {row['left_lower']} | {row['left_higher']} | {row['equal']} |"
        )

    lines += [
        "",
        "## What the grammar adds to the baseline",
        "",
        "Guessing cost is a minimum over the attacker's options, so an attacker holding",
        "both models pays `min(PCFG, zxcvbn)`. **Information added** is that minimum",
        "minus zxcvbn alone. It is never positive, and it is zero exactly when the PCFG",
        "found nothing zxcvbn had not already found.",
        "",
        "| Category | zxcvbn alone | min(PCFG, zxcvbn) | Information added | Improved |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in report["pcfg_vs_baseline"]:
        lines.append(
            f"| {row['category']} | {row['baseline_stats']['mean_log10_guesses']:.2f} "
            f"| {row['combined_mean_log10_guesses']:.2f} "
            f"| {row['mean_information_added']:+.2f} "
            f"| {row['left_lower']}/{row['samples']} |"
        )

    lines += [
        "",
        "### All three together",
        "",
        "`min(Milestone 2, PCFG, zxcvbn)` -- the deployable object, since an attacker",
        "holds every model they can get.",
        "",
        "| Category | min of all three | Information added vs zxcvbn | Improved |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name, row in report["combined_all_three"].items():
        lines.append(
            f"| {name} | {row['mean_log10_guesses']:.2f} "
            f"| {row['mean_information_added']:+.2f} "
            f"| {row['samples_improved']}/{row['samples']} |"
        )

    lines += [
        "",
        "## PCFG against the Milestone 2 estimator",
        "",
        "Not a claim that either is right. The two price the same evidence differently:",
        "Milestone 2 charges a wordlist position and multiplies by heuristic factors;",
        "the PCFG charges a normalised probability, which includes paying for the",
        "*structure* choice that the Milestone 2 model gets for free.",
        "",
        "| Category | Milestone 2 mean | PCFG mean | Difference |",
        "| --- | ---: | ---: | ---: |",
    ]
    for row in report["pcfg_vs_indicpass"]:
        lines.append(
            f"| {row['category']} | {row['indicpass_stats']['mean_log10_guesses']:.2f} "
            f"| {row['pcfg_stats']['mean_log10_guesses']:.2f} "
            f"| {row['mean_log10_difference']:+.2f} |"
        )

    lines += [
        "",
        "## What the grammar actually derived",
        "",
        "The category sequence of the winning derivation, per category. Shape only --",
        "no content. `floor` is how often the brute-force floor, rather than the",
        "grammar, produced the reported number; `unsupported` how often no derivation",
        "covered the password at all.",
        "",
        "| Category | Commonest derivations | word segment | floor | unsupported |",
        "| --- | --- | ---: | ---: | ---: |",
    ]
    for row in report["structures"]:
        top = ", ".join(
            f"`{s['structure']}` {s['share'] * 100:.0f}%" for s in row["structures"][:3]
        )
        lines.append(
            f"| {row['category']} | {top} | {row['word_segment_rate'] * 100:.0f}% "
            f"| {row['floor_rate'] * 100:.0f}% | {row['unsupported_rate'] * 100:.0f}% |"
        )

    fit = report["character_model"]
    populations = fit["populations"]
    floor = fit["bruteforce_floor_cost_per_character"]
    lines += [
        "",
        "## What the character model learned",
        "",
        fit["note"],
        "",
        "| Population | N | log10 cost per character |",
        "| --- | ---: | ---: |",
    ]
    for name, row in populations.items():
        lines.append(
            f"| {name.replace('_', ' ')} | {row['words']} "
            f"| {row['log10_cost_per_character']:.3f} |"
        )
    lines += [
        f"| **the brute-force floor** | -- | **{floor:.3f}** |",
        "",
        "Two readings, and the second is the one that explains the benchmark.",
        "",
        "1. **The model generalised.** Bank words the dictionary is *missing* cost "
        f"{populations['indic_bank_absent_from_dictionary']['log10_cost_per_character']:.3f} "
        "per character against "
        f"{populations['indic_bank_in_dictionary']['log10_cost_per_character']:.3f} "
        "for words it trained on. Those are the same number: it learned the shape of "
        "Romanized Hindi, not a list of spellings. Random strings cost "
        f"{populations['random_lowercase']['log10_cost_per_character']:.3f}, so the "
        "discrimination is real and large.",
        "",
        "2. **The margin over the floor is not.** Only the gap between the model and "
        "the floor can ever reach a reported estimate, and that gap is "
        f"{_margin(fit):+.3f} "
        "log10 per character on unseen Hindi -- a fraction of an order of magnitude on "
        "a whole word, and less than the structure and category priors charge for "
        "using the category at all. This is why the `no_character_model` ablation "
        "moves nothing, and it is a fact about the flat-10 floor Milestone 2 adopted "
        "rather than about the character model.",
    ]

    control = report["random_control"]
    lines += [
        "",
        "## The random control",
        "",
        "The control that decides whether any Indic result is believable. A grammar",
        "that also lowered random strings would be finding structure that is not there,",
        "and the Indic effect would be the same artefact.",
        "",
        control["note"],
        "",
        f"{control['samples_per_cell']} random strings per cell, seed {control['seed']}, "
        "deterministic.",
        "",
        "| Alphabet | Length | Derivation contains a word | Grammar below brute force "
        "| Mean grammar - brute force |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['alphabet']} | {row['length']} | {row['word_rate'] * 100:.0f}% "
        f"| **{row['below_bruteforce_rate'] * 100:.1f}%** "
        f"| {row['mean_grammar_minus_bruteforce']:+.2f} |"
        for row in control["rows"]
    ]
    lines += [
        "",
        f"Worst cell: {control['worst_word_rate'] * 100:.0f}% of random strings had a "
        "dictionary segment in the winning derivation, and "
        f"**{control['worst_below_bruteforce_rate'] * 100:.1f}%** were priced below "
        "enumerating them.",
        "",
    ]

    if report["ablations"]:
        lines += [
            "## Ablations",
            "",
            "Each arm is the shipped configuration with exactly one thing changed, fitted",
            "from scratch -- grammar **and** guess curve, because a curve built for one",
            "grammar says nothing about another. Cells are the arm's mean log10 minus the",
            "shipped configuration's, per category. Positive means the change made",
            "passwords look stronger.",
            "",
            "| Arm | " + " | ".join(CATEGORIES) + " |",
            "| --- | " + " | ".join("---:" for _ in CATEGORIES) + " |",
        ]
        for arm in report["ablations"]:
            cells = " | ".join(
                f"{arm['delta_vs_shipped'].get(name, 0.0):+.2f}" for name in CATEGORIES
            )
            lines.append(f"| `{arm['name']}` | {cells} |")

        lines += ["", "| Arm | What it changes |", "| --- | --- |"]
        lines += [f"| `{a['name']}` | {a['description']} |" for a in report["ablations"]]

    lines += ["", "---", "", f"*{report['interpretation_note']}*", ""]
    return "\n".join(lines) + "\n"


def render_targeted(report: dict[str, Any]) -> str:
    lines = _header_lines(report, "PCFG targeted cases and random control")
    lines += [
        "## The question",
        "",
        f"> {report['question']}",
        "",
        report["redaction_note"],
        "",
        "## Cases",
        "",
        "`G` is the reported PCFG estimate, `grammar` what the model said before the",
        "brute-force floor, `bf` what enumerating the string would cost. When",
        "`grammar > bf` the floor won and the grammar contributed nothing.",
        "",
        "| Case | Family | Len | Derivation | log10 P | grammar | bf | **PCFG G** "
        "| M2 | zxcvbn | min(PCFG,zx) |",
        "| --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["cases"]:
        pcfg = row["pcfg"]
        structure = "+".join(pcfg["structure"]) or "*unsupported*"
        meter = row.get("indicpass", {})
        baseline = row.get("zxcvbn", {})
        lines.append(
            f"| `{row['case_id']}` | {row['family']} | {row['length']} | `{structure}` "
            f"| {pcfg['log10_probability']:.2f} | {pcfg['grammar_log10_guesses']:.2f} "
            f"| {pcfg['bruteforce_log10_guesses']:.1f} "
            f"| **{pcfg['log10_guesses']:.2f}** "
            f"| {meter.get('log10_guesses', float('nan')):.2f} "
            f"| {baseline.get('log10_guesses', float('nan')):.2f} "
            f"| {row.get('combined_log10_guesses', float('nan')):.2f} |"
        )

    lines += ["", "## What each case tests", "", "| Case | Note |", "| --- | --- |"]
    lines += [f"| `{row['case_id']}` | {row['note']} |" for row in report["cases"]]

    control = report["random_control"]
    lines += [
        "",
        "## Random control, full sweep",
        "",
        control["note"],
        "",
        f"{control['samples_per_cell']} strings per cell, seed {control['seed']}.",
        "",
        "| Alphabet | Length | word in derivation | grammar < brute force "
        "| mean(grammar - bf) | mean vs zxcvbn |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in control["rows"]:
        against = row.get("mean_vs_baseline")
        lines.append(
            f"| {row['alphabet']} | {row['length']} | {row['word_rate'] * 100:.0f}% "
            f"| **{row['below_bruteforce_rate'] * 100:.1f}%** "
            f"| {row['mean_grammar_minus_bruteforce']:+.2f} "
            f"| {'--' if against is None else f'{against:+.2f}'} |"
        )
    lines.append("")
    return "\n".join(lines) + "\n"


# -- console ---------------------------------------------------------------


def print_console(report: dict[str, Any]) -> None:
    by_estimator = report["by_estimator"]
    print(f"\n{'=' * 92}")
    print("PCFG BENCHMARK -- IndicPass PCFG vs "
          f"{report['baseline']['name']} {report['baseline']['version']}")
    print(f"{'=' * 92}")
    print(f"  {'category':<16}{'N':>5}{'M2 med':>9}{'PCFG med':>10}{'zx med':>9}"
          f"{'diff':>9}{'info+':>9}{'improved':>10}{'word%':>8}")
    census = {row["category"]: row for row in report["structures"]}
    for row in report["pcfg_vs_baseline"]:
        name = row["category"]
        print(
            f"  {name:<16}{row['samples']:>5}"
            f"{by_estimator['indicpass'][name]['median_log10_guesses']:>9.2f}"
            f"{row['pcfg_stats']['median_log10_guesses']:>10.2f}"
            f"{row['baseline_stats']['median_log10_guesses']:>9.2f}"
            f"{row['mean_log10_difference']:>+9.2f}"
            f"{row['mean_information_added']:>+9.2f}"
            f"{row['left_lower']:>7}/{row['samples']:<3}"
            f"{census[name]['word_segment_rate'] * 100:>7.0f}%"
        )
    control = report["random_control"]
    print()
    print(f"  random control: worst word rate {control['worst_word_rate'] * 100:.0f}%, "
          f"worst below-brute-force rate "
          f"{control['worst_below_bruteforce_rate'] * 100:.1f}%")
    print()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("Benchmark one language at a time. Pass --languages hin.")
        return 2
    language = languages[0]

    evaluation = config.password_section("evaluation")
    pcfg_config = config.password_section("pcfg")
    pcfg_evaluation = pcfg_config.get("evaluation") or {}
    scoring = config.password_section("scoring")
    matching = config.password_section("matching")
    dictionary_config = config.password_section("dictionary")

    seed = args.seed if args.seed is not None else int(evaluation.get("seed", 42))
    per_category = args.samples or int(
        (evaluation.get("benchmark") or {}).get("samples_per_category", 200)
    )
    control_samples = args.control_samples or int(
        pcfg_evaluation.get("random_control_samples", 300)
    )

    try:
        baseline = load_baseline(
            str(config.password_section("baseline").get("implementation", "zxcvbn"))
        )
    except BaselineUnavailable as exc:
        logger.error("%s", exc)
        return 2

    tiers = list(dictionary_config.get("tiers") or [])
    tier_order = [str(tier["name"]) for tier in tiers]
    named = [str(tier["name"]) for tier in tiers if tier.get("named_entity")]
    path = config.resolve(
        args.dictionary or (dictionary_config.get("files") or {})[language.code]
    )

    logger.info("Loading %s", config.relative(path))
    dictionary = IndicDict.load(path, language=language.code, tier_order=tier_order)
    scale = StrengthScale.from_config(config.password_section("strength"))

    grammar_settings = GrammarSettings.from_config(pcfg_config, scoring)
    estimator_settings = EstimatorSettings.from_config(pcfg_config, scoring)
    if args.curve_samples:
        estimator_settings = dataclasses.replace(estimator_settings, samples=args.curve_samples)

    started = time.perf_counter()
    grammar = PcfgGrammar.train(dictionary, grammar_settings)
    estimator = PcfgEstimator.train(grammar, settings=estimator_settings, scale=scale)
    logger.info(
        "Grammar and guess curve fitted in %.1fs (%s samples)",
        time.perf_counter() - started,
        f"{estimator.curve.samples:,}",
    )

    meter = IndicPassMeter(
        [dictionary],
        matcher_settings=MatcherSettings.from_config(matching, scoring),
        scoring_settings=ScoringSettings.from_config(scoring, matching),
        scale=scale,
        named_entity_tiers=named,
        baseline=baseline,
        pcfg=estimator,
    )

    corpus = generate_corpus(seed=seed, samples_per_category=per_category)
    logger.info(
        "Generated %d samples across %d categories (seed %d, generator %s)",
        len(corpus), len(CATEGORIES), seed, GENERATOR_VERSION,
    )

    started = time.perf_counter()
    results = score_corpus(meter, corpus)
    logger.info("Scored %d samples in %.1fs", len(results), time.perf_counter() - started)

    started = time.perf_counter()
    control = random_control_probe(
        estimator, seed=seed, samples=control_samples, baseline=baseline
    )
    logger.info("Random control swept in %.1fs", time.perf_counter() - started)

    cases = score_targeted_cases(estimator, meter=meter, baseline=baseline)
    logger.info("Scored %d targeted cases", len(cases))

    character_model = character_model_fit(estimator, seed=seed)
    logger.info(
        "Character model cost per character: %s",
        {
            name: row["log10_cost_per_character"]
            for name, row in character_model["populations"].items()
        },
    )

    arms: list[Arm] = []
    if not args.no_ablations:
        for template in ABLATION_ARMS:
            arm = dataclasses.replace(template, results=[])
            started = time.perf_counter()
            variant = build_arm(
                arm,
                dictionary=dictionary,
                grammar_settings=grammar_settings,
                estimator_settings=estimator_settings,
                scale=scale,
            )
            arm.results = score_corpus(
                IndicPassMeter(
                    [dictionary],
                    matcher_settings=meter.matcher.settings,
                    scoring_settings=meter.scoring_settings,
                    scale=scale,
                    named_entity_tiers=named,
                    pcfg=variant,
                ),
                corpus,
            )
            arms.append(arm)
            logger.info("  %-22s fitted and scored in %.1fs",
                        arm.name, time.perf_counter() - started)

    header = _header(
        config,
        dictionary_info=describe_dictionaries(meter),
        corpus=corpus,
        baseline=baseline,
        estimator=estimator,
        dictionary=dictionary,
        seed=seed,
    )

    benchmark = build_benchmark_report(
        header=header,
        results=results,
        arms=arms,
        control=control,
        character_model=character_model,
    )
    targeted = build_targeted_report(header=header, cases=cases, control=control)
    print_console(benchmark)

    if args.no_report:
        return 0

    directory = (
        config.resolve(args.report_dir) if args.report_dir else config.ensure_dir("reports")
    )
    directory.mkdir(parents=True, exist_ok=True)
    reports = {
        f"{pcfg_evaluation.get('report_prefix', 'pcfg_benchmark')}_{language.code}": (
            benchmark, render_benchmark,
        ),
        f"{pcfg_evaluation.get('targeted_prefix', 'pcfg_targeted')}_{language.code}": (
            targeted, render_targeted,
        ),
    }
    for name, (payload, render) in reports.items():
        base = directory / name
        base.with_suffix(".json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        base.with_suffix(".md").write_text(render(payload), encoding="utf-8")
        logger.info("Report written to %s", config.relative(base.with_suffix(".md")))

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
