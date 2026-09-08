#!/usr/bin/env python
"""Compare IndicPass with a generic estimator on a controlled password set.

    python scripts/password_benchmark.py
    python scripts/password_benchmark.py --samples 50 --no-report     # smoke run

The question
------------
    Does explicit Romanized-Indic lexical modelling reduce estimated guess
    counts for Romanized Indic passwords, relative to a generic
    password-strength estimator?

Both estimators score the *same* passwords in the *same* call, and the results
are reported per category. An overall average across seven deliberately
different populations would answer nothing.

What a lower number does and does not mean
------------------------------------------
A lower IndicPass estimate on the Indic categories means IndicPass found
weakness the baseline missed -- which is the hypothesis. It does **not** by
itself mean IndicPass is more accurate: that needs a reference attack against
real leaked passwords, which this project does not have. The random and English
categories are in the corpus to catch the failure mode where IndicPass reads
lower for reasons unrelated to the lexicon.

Three reports come out of one run, because they share a corpus and a scoring
pass and would be incomparable if they did not:

``password_benchmark_<lang>``
    The comparison, plus the dictionary on/off ablation.
``mined_tier_ablation``
    Whether the largest and least precise tier is carrying the result.
``guess_model_sensitivity``
    How much of the difference survives changing the brute-force alphabet
    assumption, the match-class penalties, and the frequency source.

No password is written to any of them. Rows are keyed on ``sample_id``, and the
corpus regenerates exactly from ``evaluation.seed``.
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
    aggregate_all,
    compare_all,
    false_match_probe,
    overall,
    score_corpus,
)
from indicpass.password.matcher import MatcherSettings
from indicpass.password.meter import IndicPassMeter, describe_dictionaries
from indicpass.password.scoring import ScoringSettings, StrengthScale

SCRIPT = "password_benchmark"

#: Categories where the Indic lexicon is expected to help. Named here so the
#: report can state the hypothesis and its controls separately rather than
#: letting a reader pick whichever subset flatters the result.
INDIC_CATEGORIES = ("indic_word", "indic_numeric", "indic_year", "indic_symbol")
CONTROL_CATEGORIES = ("english", "random")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="password_benchmark.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--samples", type=int, metavar="N", help="Samples per category. Default from config."
    )
    parser.add_argument("--seed", type=int, metavar="N", help="Corpus seed. Default from config.")
    parser.add_argument(
        "--dictionary", type=Path, metavar="FILE", help="Dictionary to use. Default from config."
    )
    parser.add_argument(
        "--report-dir", type=Path, metavar="DIR", help="Where the reports land."
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


# -- variants --------------------------------------------------------------


@dataclasses.dataclass
class Variant:
    """One configuration of the meter, and why it is in the experiment."""

    name: str
    description: str
    meter: IndicPassMeter
    results: list[SampleResult] = dataclasses.field(default_factory=list)


def _dictionary_without(dictionary: IndicDict, tier: str, tier_order: Sequence[str]) -> IndicDict:
    """The same dictionary with one provenance tier removed.

    Re-ranked from scratch: dropping 120k entries changes where every fallback
    word sits, and a run that kept the old offsets would price against a
    wordlist it was not using.
    """
    return IndicDict.from_entries(
        (entry for entry in dictionary.entries.values() if entry.tier != tier),
        language=dictionary.language,
        tier_order=tier_order,
        frequency_source=dictionary.frequency_source,
    )


def _dictionary_without_frequency(
    dictionary: IndicDict, tier_order: Sequence[str]
) -> IndicDict:
    """The Milestone 1 artefact: every entry priced by its provenance tier."""
    return IndicDict.from_entries(
        (
            dataclasses.replace(
                entry, frequency=None, rank=None, frequency_source=None,
                frequency_matched_via=None,
            )
            for entry in dictionary.entries.values()
        ),
        language=dictionary.language,
        tier_order=tier_order,
    )


def build_variants(
    *,
    dictionary: IndicDict,
    tier_order: Sequence[str],
    named_entity_tiers: Sequence[str],
    matcher_settings: MatcherSettings,
    scoring_settings: ScoringSettings,
    scale: StrengthScale,
    baseline: Any,
) -> list[Variant]:
    """Every arm of the experiment, sharing one baseline and one scale."""

    def meter(dict_: IndicDict, matching: MatcherSettings, scoring: ScoringSettings):
        return IndicPassMeter(
            [dict_],
            matcher_settings=matching,
            scoring_settings=scoring,
            scale=scale,
            named_entity_tiers=named_entity_tiers,
            baseline=baseline,
        )

    empty = IndicDict.from_entries([], language=dictionary.language, tier_order=tier_order)

    return [
        Variant(
            "indicpass",
            "The shipped configuration. Every other arm is this with one thing changed.",
            meter(dictionary, matcher_settings, scoring_settings),
        ),
        Variant(
            "no_dictionary",
            "Ablation B: the same meter with an empty dictionary. Isolates what the "
            "Indic lexicon contributes from what generic pattern scoring does.",
            meter(empty, matcher_settings, scoring_settings),
        ),
        Variant(
            "no_mined_tier",
            "Ablation D: the mined tier dropped. It is the largest and least precise "
            "source, and a result that rests on it is a result about corpus noise.",
            meter(_dictionary_without(dictionary, "mined", tier_order), matcher_settings,
                  scoring_settings),
        ),
        Variant(
            "no_frequency",
            "The Milestone 1 pricing: provenance tier only, no observed frequency. "
            "Isolates what the external frequency table bought.",
            meter(_dictionary_without_frequency(dictionary, tier_order), matcher_settings,
                  scoring_settings),
        ),
        Variant(
            "observed_cardinality",
            "Brute-force alphabet taken from the character classes present (26/36/95) "
            "instead of the shipped flat 10. The Milestone 1 policy, and the one that "
            "made the whole random-control divergence.",
            meter(
                dictionary,
                matcher_settings,
                dataclasses.replace(scoring_settings, bruteforce_cardinality="observed"),
            ),
        ),
        Variant(
            "no_substring_matches",
            "Only whole-password dictionary hits count. The strictest reading of "
            "'prefer exact matches'.",
            meter(
                dictionary,
                dataclasses.replace(matcher_settings, allow_substring_matches=False),
                scoring_settings,
            ),
        ),
        Variant(
            "no_fragment_matches",
            "Sub-threshold hits dropped rather than penalised.",
            meter(
                dictionary,
                dataclasses.replace(matcher_settings, allow_fragment_matches=False),
                scoring_settings,
            ),
        ),
        Variant(
            "fragment_penalty_1",
            "Fragments priced identically to real words -- the uncorrected behaviour "
            "the class penalty exists to fix.",
            meter(
                dictionary,
                dataclasses.replace(
                    matcher_settings,
                    class_penalties={**matcher_settings.class_penalties, "fragment": 1.0},
                ),
                scoring_settings,
            ),
        ),
        Variant(
            "min_substring_6",
            "The substring threshold raised from 4 to 6, where a random hit has "
            "probability 2e-4 rather than 0.055.",
            meter(
                dictionary,
                dataclasses.replace(matcher_settings, min_substring_length=6),
                scoring_settings,
            ),
        ),
    ]


# -- report assembly -------------------------------------------------------


def _header(config: Config, dictionary_info: Any, corpus: Sequence[BenchmarkSample],
            baseline: Any, seed: int) -> dict[str, Any]:
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": f"{config.name} v{config.version}",
        "git_commit": git_commit(config.root),
        "corpus": {"seed": seed, **describe_corpus(corpus)},
        "baseline": baseline.describe(),
        "dictionaries": dictionary_info,
    }


def _variant_table(variants: Sequence[Variant]) -> list[dict[str, Any]]:
    return [{"name": v.name, "description": v.description} for v in variants]


def build_benchmark_report(
    *, header: dict[str, Any], variants: dict[str, Variant]
) -> dict[str, Any]:
    main = variants["indicpass"]
    comparisons = compare_all(main.results)
    return {
        **header,
        "question": (
            "Does explicit Romanized-Indic lexical modelling reduce estimated guess "
            "counts for Romanized Indic passwords, relative to a generic estimator?"
        ),
        "hypothesis_categories": list(INDIC_CATEGORIES),
        "control_categories": list(CONTROL_CATEGORIES),
        "comparison": [c.to_dict() for c in comparisons],
        "overall": overall(main.results),
        "dictionary_ablation": {
            "description": (
                "Ablation A vs B: the same meter with and without the Indic dictionary. "
                "The difference is what the lexicon contributes; the remainder is "
                "generic pattern scoring that any estimator would do."
            ),
            "with_dictionary": [s.to_dict() for s in aggregate_all(main.results)],
            "without_dictionary": [
                s.to_dict() for s in aggregate_all(variants["no_dictionary"].results)
            ],
        },
        "samples": [row.to_dict() for row in main.results],
    }


def build_mined_report(*, header: dict[str, Any], variants: dict[str, Variant]) -> dict[str, Any]:
    return {
        **header,
        "question": (
            "Is the mined tier -- the largest and least precise source -- carrying the "
            "result, or is it adding noise?"
        ),
        "arms": _variant_table(
            [variants["indicpass"], variants["no_mined_tier"], variants["no_dictionary"]]
        ),
        "all_tiers": [s.to_dict() for s in aggregate_all(variants["indicpass"].results)],
        "without_mined": [s.to_dict() for s in aggregate_all(variants["no_mined_tier"].results)],
        "without_dictionary": [
            s.to_dict() for s in aggregate_all(variants["no_dictionary"].results)
        ],
        "comparison_all_tiers": [c.to_dict() for c in compare_all(variants["indicpass"].results)],
        "comparison_without_mined": [
            c.to_dict() for c in compare_all(variants["no_mined_tier"].results)
        ],
    }


SENSITIVITY_ARMS = (
    "observed_cardinality",
    "no_frequency",
    "no_substring_matches",
    "no_fragment_matches",
    "fragment_penalty_1",
    "min_substring_6",
)


def build_sensitivity_report(
    *, header: dict[str, Any], variants: dict[str, Variant], seed: int
) -> dict[str, Any]:
    baseline_arm = variants["indicpass"]
    reference = {name: s.to_dict() for name, s in _by_category(baseline_arm)}

    arms = []
    for name in SENSITIVITY_ARMS:
        variant = variants[name]
        stats = dict(_by_category(variant))
        arms.append(
            {
                "name": name,
                "description": variant.description,
                "by_category": [stats[c].to_dict() for c in CATEGORIES if c in stats],
                "delta_vs_shipped": {
                    category: round(
                        stats[category].mean_log10_guesses
                        - reference[category]["mean_log10_guesses"],
                        4,
                    )
                    for category in stats
                },
            }
        )

    return {
        **header,
        "question": (
            "How much of the shipped configuration's behaviour survives changing the "
            "brute-force alphabet assumption, the match-class policy, and the frequency "
            "source?"
        ),
        "shipped": [s.to_dict() for s in aggregate_all(baseline_arm.results)],
        "arms": arms,
        # Not a category of the benchmark: a separate, deterministic sweep over
        # random strings that exists to answer "does a 298k wordlist make
        # arbitrary text look predictable?" independently of the corpus.
        "false_matches": {
            "shipped": false_match_probe(baseline_arm.meter, seed=seed),
            "fragment_penalty_1": false_match_probe(
                variants["fragment_penalty_1"].meter, seed=seed
            ),
            "no_fragment_matches": false_match_probe(
                variants["no_fragment_matches"].meter, seed=seed
            ),
        },
        "cardinality_note": (
            "Both estimators now charge a flat 10 guesses per unexplained character, so "
            "they differ in their lexicon and not in this. The observed_cardinality arm "
            "restores the classical alphabet-size model (26/36/95) that IndicPass shipped "
            "with in Milestone 1: it was responsible for essentially the whole divergence "
            "from the baseline on random controls, where there is no lexical structure to "
            "find and therefore nothing the Indic dictionary could have contributed."
        ),
    }


def _by_category(variant: Variant):
    for stats in aggregate_all(variant.results):
        yield stats.category, stats


# -- markdown --------------------------------------------------------------


def _header_lines(report: dict[str, Any], title: str) -> list[str]:
    corpus = report["corpus"]
    dictionaries = report["dictionaries"]
    entry = dictionaries[0] if dictionaries else {}
    source = (entry.get("frequency_source") or {}).get("identifier", "none")
    return [
        f"# {title}",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Git commit:** `{report['git_commit']}`",
        f"- **Baseline:** {report['baseline']['name']} {report['baseline']['version']}",
        f"- **Dictionary:** {entry.get('entries', 0):,} entries, "
        f"{entry.get('ranked_entries', 0):,} priced by measured rank "
        f"({entry.get('frequency_coverage', 0) * 100:.1f}%)",
        f"- **Frequency source:** `{source}`",
        f"- **Corpus:** {corpus['total_samples']:,} generated samples, seed "
        f"{corpus['seed']}, generator {corpus['generator_version']}",
        "",
        "Rows are keyed on `sample_id`. **No row maps an id to a password**, and no",
        "composed password -- word plus digits, symbol, year, or any random string --",
        "is written anywhere. The corpus regenerates exactly from the seed above, which",
        "is what reproducibility requires; storing the strings is not.",
        "",
        "(Single-word samples are, by construction, the word banks in",
        "`src/indicpass/password/benchmark.py`. Those are committed source and are",
        "printed in the coverage tables on purpose -- they are the measuring instrument.",
        "Seeing a word there discloses nothing about which sample used it.)",
        "",
    ]


def _stats_table(rows: Sequence[dict[str, Any]], label: str) -> list[str]:
    lines = [
        f"| Category | N | {label} mean log10 | median log10 | mean score | match rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['category']} | {row['samples']} | {row['mean_log10_guesses']:.2f} "
        f"| {row['median_log10_guesses']:.2f} | {row['mean_score']:.2f} "
        f"| {row['match_rate'] * 100:.0f}% |"
        for row in rows
    ]
    return lines


def render_benchmark(report: dict[str, Any]) -> str:
    lines = _header_lines(report, "Password benchmark -- IndicPass vs zxcvbn")
    lines += [
        "## The question",
        "",
        f"> {report['question']}",
        "",
        f"Hypothesis categories: {', '.join(f'`{c}`' for c in report['hypothesis_categories'])}. "
        f"Controls: {', '.join(f'`{c}`' for c in report['control_categories'])}.",
        "",
        "## Comparison by category",
        "",
        "`Difference` is mean log10(IndicPass) - mean log10(zxcvbn). **Negative means",
        "IndicPass estimates fewer guesses.** Lower is not automatically more accurate:",
        "that would require a reference attack model, which this project does not have.",
        "",
        "| Category | N | IndicPass median log10 | zxcvbn median log10 | Median diff "
        "| Mean diff | IP lower | IP higher | equal |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["comparison"]:
        lines.append(
            f"| {row['category']} | {row['samples']} "
            f"| {row['indicpass']['median_log10_guesses']:.2f} "
            f"| {row['baseline']['median_log10_guesses']:.2f} "
            f"| {row['median_log10_difference']:+.2f} "
            f"| {row['mean_log10_difference']:+.2f} "
            f"| {row['indicpass_lower']} | {row['indicpass_higher']} | {row['equal']} |"
        )

    lines += [
        "",
        "## What the Indic lexicon adds to the baseline",
        "",
        "The table above asks whether IndicPass *beats* zxcvbn, which is the wrong",
        "question: IndicPass has no common-password wordlist and was never going to win",
        "outright on English. The question the experiment actually poses is whether the",
        "Indic lexicon carries information the generic estimator lacks.",
        "",
        "Guessing cost is a minimum over the attacker's options, so an attacker holding",
        "both wordlists pays `min(IndicPass, zxcvbn)`. **Information added** is that",
        "minimum minus zxcvbn alone: how much cheaper the password becomes once Indic",
        "lexical knowledge is available. It is never positive, and it is zero exactly",
        "when IndicPass found nothing the baseline had not already found.",
        "",
        "| Category | zxcvbn alone | min(IndicPass, zxcvbn) | Information added (mean) "
        "| (median) | Samples improved |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["comparison"]:
        lines.append(
            f"| {row['category']} | {row['baseline']['mean_log10_guesses']:.2f} "
            f"| {row['combined_mean_log10_guesses']:.2f} "
            f"| {row['mean_information_added']:+.2f} "
            f"| {row['median_information_added']:+.2f} "
            f"| {row['indicpass_lower']}/{row['samples']} |"
        )

    lines += [
        "",
        "## Strength scores",
        "",
        "| Category | IndicPass mean | zxcvbn mean | IndicPass median | zxcvbn median "
        "| Disagreements |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["comparison"]:
        lines.append(
            f"| {row['category']} | {row['indicpass']['mean_score']:.2f} "
            f"| {row['baseline']['mean_score']:.2f} "
            f"| {row['indicpass']['median_score']:.1f} "
            f"| {row['baseline']['median_score']:.1f} "
            f"| {row['score_disagreements']}/{row['samples']} |"
        )

    ablation = report["dictionary_ablation"]
    lines += [
        "",
        "## Ablation A/B -- the Indic dictionary",
        "",
        ablation["description"],
        "",
        "| Category | With dictionary | Without | Effect of the lexicon |",
        "| --- | ---: | ---: | ---: |",
    ]
    without = {row["category"]: row for row in ablation["without_dictionary"]}
    for row in ablation["with_dictionary"]:
        other = without[row["category"]]
        delta = row["mean_log10_guesses"] - other["mean_log10_guesses"]
        lines.append(
            f"| {row['category']} | {row['mean_log10_guesses']:.2f} "
            f"| {other['mean_log10_guesses']:.2f} | {delta:+.2f} |"
        )

    lines += [
        "",
        "## Match rates",
        "",
        "How often the dictionary contributed at all, and how often the hit was priced",
        "by a measured rank rather than a provenance-tier fallback.",
        "",
        "| Category | Any dictionary hit | Hit priced by measured rank |",
        "| --- | ---: | ---: |",
    ]
    lines += [
        f"| {row['category']} | {row['indicpass']['match_rate'] * 100:.0f}% "
        f"| {row['indicpass']['ranked_match_rate'] * 100:.0f}% |"
        for row in report["comparison"]
    ]

    lines += [
        "",
        "## Overall",
        "",
        f"{report['overall']['samples']:,} samples, mean log10 "
        f"{report['overall']['mean_log10_guesses']:.2f}, median "
        f"{report['overall']['median_log10_guesses']:.2f}.",
        "",
        f"*{report['overall']['note']}*",
        "",
    ]
    return "\n".join(lines) + "\n"


def render_mined(report: dict[str, Any]) -> str:
    lines = _header_lines(report, "Mined-tier ablation")
    lines += [
        "## The question",
        "",
        f"> {report['question']}",
        "",
        "The mined tier is 120,000 of the dictionary's 297,747 entries, automatically",
        "extracted from monolingual and parallel corpora. Only ~2% of it has an observed",
        "corpus frequency, so almost all of it is priced by the tier fallback -- and a",
        "fallback-priced hit is a policy, not a measurement.",
        "",
        "## Arms",
        "",
        "| Arm | What it is |",
        "| --- | --- |",
    ]
    lines += [f"| `{arm['name']}` | {arm['description']} |" for arm in report["arms"]]

    lines += [
        "",
        "## Effect on the estimate",
        "",
        "| Category | All tiers | Without mined | Difference | Without any dictionary |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    without = {row["category"]: row for row in report["without_mined"]}
    nodict = {row["category"]: row for row in report["without_dictionary"]}
    for row in report["all_tiers"]:
        category = row["category"]
        delta = without[category]["mean_log10_guesses"] - row["mean_log10_guesses"]
        lines.append(
            f"| {category} | {row['mean_log10_guesses']:.2f} "
            f"| {without[category]['mean_log10_guesses']:.2f} | {delta:+.2f} "
            f"| {nodict[category]['mean_log10_guesses']:.2f} |"
        )

    lines += [
        "",
        "## Match rates",
        "",
        "| Category | Match rate, all tiers | Match rate, without mined |",
        "| --- | ---: | ---: |",
    ]
    lines += [
        f"| {row['category']} | {row['match_rate'] * 100:.0f}% "
        f"| {without[row['category']]['match_rate'] * 100:.0f}% |"
        for row in report["all_tiers"]
    ]

    lines += [
        "",
        "## Comparison against the baseline, with and without the mined tier",
        "",
        "| Category | Mean diff, all tiers | Mean diff, without mined |",
        "| --- | ---: | ---: |",
    ]
    trimmed = {row["category"]: row for row in report["comparison_without_mined"]}
    lines += [
        f"| {row['category']} | {row['mean_log10_difference']:+.2f} "
        f"| {trimmed[row['category']]['mean_log10_difference']:+.2f} |"
        for row in report["comparison_all_tiers"]
    ]
    lines.append("")
    return "\n".join(lines) + "\n"


def render_sensitivity(report: dict[str, Any]) -> str:
    lines = _header_lines(report, "Guess-model sensitivity")
    lines += [
        "## The question",
        "",
        f"> {report['question']}",
        "",
        "## Brute-force cardinality",
        "",
        report["cardinality_note"],
        "",
        "## Shipped configuration",
        "",
    ]
    lines += _stats_table(report["shipped"], "IndicPass")

    lines += [
        "",
        "## Effect of each change on mean log10(guesses)",
        "",
        "Each cell is the arm's mean minus the shipped configuration's mean, per",
        "category. Positive means the change made passwords look stronger.",
        "",
        "| Arm | " + " | ".join(CATEGORIES) + " |",
        "| --- | " + " | ".join("---:" for _ in CATEGORIES) + " |",
    ]
    for arm in report["arms"]:
        cells = " | ".join(
            f"{arm['delta_vs_shipped'].get(category, 0.0):+.2f}" for category in CATEGORIES
        )
        lines.append(f"| `{arm['name']}` | {cells} |")

    probe = report["false_matches"]
    shipped = probe["shipped"]
    lines += [
        "",
        "## False matches on random controls",
        "",
        f"{shipped['samples_per_cell']} random strings per cell, seed {shipped['seed']}, "
        "deterministic.",
        "",
        shipped["note"],
        "",
        "| Alphabet | Length | Offered | mean | median | **Accepted** | mean | median |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['alphabet']} | {row['length']} | {row['offered_rate'] * 100:.0f}% "
        f"| {row['mean_offered']:.2f} | {row['median_offered']:.0f} "
        f"| **{row['accepted_rate'] * 100:.0f}%** | {row['mean_accepted']:.2f} "
        f"| {row['median_accepted']:.0f} |"
        for row in shipped["rows"]
    ]
    lines += [
        "",
        "Worst accepted rate across all cells: "
        f"**{shipped['worst_accepted_rate'] * 100:.1f}%**.",
        "",
        "### Effect of the fragment policy on false matches",
        "",
        "| Configuration | Worst accepted rate |",
        "| --- | ---: |",
        f"| shipped (fragment penalty 10x) | {shipped['worst_accepted_rate'] * 100:.1f}% |",
        "| fragments priced as words | "
        f"{probe['fragment_penalty_1']['worst_accepted_rate'] * 100:.1f}% |",
        "| fragments dropped entirely | "
        f"{probe['no_fragment_matches']['worst_accepted_rate'] * 100:.1f}% |",
        "",
        "## What each arm is",
        "",
        "| Arm | What it changes |",
        "| --- | --- |",
    ]
    lines += [f"| `{arm['name']}` | {arm['description']} |" for arm in report["arms"]]

    for arm in report["arms"]:
        lines += ["", f"### `{arm['name']}`", ""]
        lines += _stats_table(arm["by_category"], arm["name"])
    lines.append("")
    return "\n".join(lines) + "\n"


# -- console ---------------------------------------------------------------


def print_console(report: dict[str, Any]) -> None:
    print(f"\n{'=' * 86}")
    print("PASSWORD BENCHMARK -- IndicPass vs "
          f"{report['baseline']['name']} {report['baseline']['version']}")
    print(f"{'=' * 86}")
    print(f"  {'category':<16}{'N':>5}{'IP med':>9}{'zx med':>9}{'med diff':>10}"
          f"{'IP<zx':>8}{'IP>zx':>8}{'match':>8}")
    for row in report["comparison"]:
        print(
            f"  {row['category']:<16}{row['samples']:>5}"
            f"{row['indicpass']['median_log10_guesses']:>9.2f}"
            f"{row['baseline']['median_log10_guesses']:>9.2f}"
            f"{row['median_log10_difference']:>+10.2f}"
            f"{row['indicpass_lower']:>8}{row['indicpass_higher']:>8}"
            f"{row['indicpass']['match_rate'] * 100:>7.0f}%"
        )
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
    benchmark_config = evaluation.get("benchmark") or {}
    seed = args.seed if args.seed is not None else int(evaluation.get("seed", 42))
    per_category = args.samples or int(benchmark_config.get("samples_per_category", 200))

    baseline_config = config.password_section("baseline")
    try:
        baseline = load_baseline(str(baseline_config.get("implementation", "zxcvbn")))
    except BaselineUnavailable as exc:
        logger.error("%s", exc)
        return 2

    dictionary_config = config.password_section("dictionary")
    tiers = list(dictionary_config.get("tiers") or [])
    tier_order = [str(tier["name"]) for tier in tiers]
    named = [str(tier["name"]) for tier in tiers if tier.get("named_entity")]
    path = config.resolve(
        args.dictionary or (dictionary_config.get("files") or {})[language.code]
    )

    logger.info("Loading %s", config.relative(path))
    dictionary = IndicDict.load(path, language=language.code, tier_order=tier_order)
    logger.info(
        "  %d entries, %d priced by measured rank (%.1f%%)",
        len(dictionary),
        dictionary.ranked_total,
        dictionary.frequency_coverage * 100,
    )

    corpus = generate_corpus(seed=seed, samples_per_category=per_category)
    logger.info(
        "Generated %d samples across %d categories (seed %d, generator %s)",
        len(corpus),
        len(CATEGORIES),
        seed,
        GENERATOR_VERSION,
    )

    variants = build_variants(
        dictionary=dictionary,
        tier_order=tier_order,
        named_entity_tiers=named,
        matcher_settings=MatcherSettings.from_config(
            config.password_section("matching"), config.password_section("scoring")
        ),
        scoring_settings=ScoringSettings.from_config(
            config.password_section("scoring"), config.password_section("matching")
        ),
        scale=StrengthScale.from_config(config.password_section("strength")),
        baseline=baseline,
    )

    for variant in variants:
        started = time.perf_counter()
        variant.results = score_corpus(variant.meter, corpus)
        logger.info(
            "  %-22s scored %d samples in %.1fs",
            variant.name,
            len(variant.results),
            time.perf_counter() - started,
        )

    indexed = {variant.name: variant for variant in variants}
    header = _header(
        config, describe_dictionaries(indexed["indicpass"].meter), corpus, baseline, seed
    )

    reports = {
        f"{benchmark_config.get('report_prefix', 'password_benchmark')}_{language.code}": (
            build_benchmark_report(header=header, variants=indexed),
            render_benchmark,
        ),
        "mined_tier_ablation": (
            build_mined_report(header=header, variants=indexed),
            render_mined,
        ),
        "guess_model_sensitivity": (
            build_sensitivity_report(header=header, variants=indexed, seed=seed),
            render_sensitivity,
        ),
    }

    print_console(reports[f"{benchmark_config.get('report_prefix', 'password_benchmark')}"
                          f"_{language.code}"][0])

    if not args.no_report:
        directory = (
            config.resolve(args.report_dir) if args.report_dir else config.ensure_dir("reports")
        )
        directory.mkdir(parents=True, exist_ok=True)
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
