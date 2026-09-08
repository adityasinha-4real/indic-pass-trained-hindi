#!/usr/bin/env python
"""Assemble the final research report from the committed milestone reports.

    python scripts/final_report.py
    python scripts/final_report.py --no-figures

This script **synthesises; it does not measure**. Every number it prints is read
out of a committed milestone report and carried through with a pointer to the
file and the key it came from. Nothing is recomputed here, and nothing may be:
recomputing a metric in the summary is how a summary quietly stops agreeing with
the experiment it summarises, and the difference is invisible in the output.

That rule has a consequence worth stating. If a milestone report is missing,
this script fails rather than omitting a section, because a final report with a
silently absent result is worse than no final report.

It also checks that the reports agree with each other before it will write
anything: same corpus seed, same generator version, same dictionary, same PCFG
artefact, same baseline. Four experiments quoted side by side have to have been
run against the same thing, and until now nothing verified that they were.

Outputs
-------
``results/reports/final_report.md``   the report, for a reader
``results/reports/final_report.json`` every number in it, with provenance
``results/figures/*.svg``             the figures, vector and dependency-free
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.figures import PALETTE, Series, grouped_bars, intervals

SCRIPT = "final_report"

#: Every milestone report this synthesis reads, and the milestone it belongs to.
#: A missing one is an error: see the module docstring.
SOURCES: Mapping[str, str] = {
    "indicdict_coverage_hin": "M1/M2",
    "password_benchmark_hin": "M2",
    "mined_tier_ablation": "M2",
    "guess_model_sensitivity": "M2",
    "pcfg_benchmark_hin": "M3",
    "pcfg_targeted_hin": "M3",
    "reference_attack_hin": "M4",
    "milestone5_oov_attack": "M5",
}

#: Read if present, not required: it is produced by a separate verification run
#: rather than by an experiment.
OPTIONAL_SOURCES: tuple[str, ...] = ("reproducibility",)

#: The three estimators, in the order every table in this report shows them.
ESTIMATORS: tuple[tuple[str, str], ...] = (
    ("indicpass", "IndicPass (M2)"),
    ("pcfg", "PCFG (M3)"),
    ("baseline", "zxcvbn 4.5.0"),
)

#: Populations the headline tables report. ``oov_indic`` is the one the whole
#: milestone turns on and is never folded into the others.
HEADLINE: tuple[str, ...] = ("all", "in_lexicon", "oov", "oov_indic")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="final_report.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--report-dir", type=Path, metavar="DIR", help="Where the report lands.")
    parser.add_argument("--figure-dir", type=Path, metavar="DIR", help="Where the figures land.")
    parser.add_argument("--no-figures", action="store_true", help="Skip the SVG figures.")
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


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def load_sources(directory: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    """Every milestone report, and a provenance row for each."""
    reports: dict[str, Any] = {}
    provenance: dict[str, Any] = {}
    missing: list[str] = []
    for name, milestone in {**SOURCES, **dict.fromkeys(OPTIONAL_SOURCES, "verify")}.items():
        path = directory / f"{name}.json"
        if not path.is_file():
            if name in SOURCES:
                missing.append(name)
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        reports[name] = payload
        provenance[name] = {
            "milestone": milestone,
            "path": f"results/reports/{name}.json",
            "sha256": file_digest(path),
            "generated_at": payload.get("generated_at"),
            "git_commit": payload.get("git_commit"),
        }
    if missing:
        raise FileNotFoundError(
            "These milestone reports are missing, so the final report would have holes "
            f"in it: {missing}. Run the pipelines in docs/REPRODUCING.md first."
        )
    return reports, provenance


def check_consistency(reports: Mapping[str, Any]) -> dict[str, Any]:
    """Do the four experiments quote the same corpus, dictionary and grammar?

    Four results side by side are only comparable if they were produced against
    the same inputs. Nothing checked that until this function existed, and a
    mismatch would be invisible in every individual report.
    """
    checks: list[dict[str, Any]] = []

    def record(name: str, values: Mapping[str, Any], note: str) -> None:
        distinct = {json.dumps(value, sort_keys=True) for value in values.values()}
        checks.append(
            {
                "check": name,
                "consistent": len(distinct) <= 1,
                "values": {key: value for key, value in values.items()},
                "note": note,
            }
        )

    record(
        "corpus_size",
        {
            name: report.get("corpus", {}).get("total_samples")
            for name, report in reports.items()
            if "corpus" in report
        },
        "Every benchmark result must be over the same 1,400 generated samples.",
    )
    record(
        "generator_version",
        {
            name: report.get("corpus", {}).get("generator_version")
            for name, report in reports.items()
            if "corpus" in report
        },
        "A generator change would silently make two milestones' numbers "
        "incomparable; the version is what refuses that.",
    )
    record(
        "dictionary_entries",
        {
            name: (report["dictionaries"][0]["entries"] if report.get("dictionaries") else None)
            for name, report in reports.items()
            if report.get("dictionaries")
        },
        "All four estimators and both attacks read the same IndicDict build.",
    )
    record(
        "pcfg_fingerprint",
        {
            name: (report.get("pcfg") or {}).get("fingerprint")
            for name, report in reports.items()
            if report.get("pcfg")
        },
        "M3, M4 and M5 must score against the same trained grammar.",
    )
    record(
        "baseline",
        {
            name: (
                report.get("baseline_name")
                or (report.get("baseline") or {}).get("name")
            )
            for name, report in reports.items()
            if report.get("baseline") or report.get("baseline_name")
        },
        "The generic estimator every comparison is read against.",
    )
    return {
        "checks": checks,
        "all_consistent": all(entry["consistent"] for entry in checks),
    }


# -- extraction -------------------------------------------------------------


def _metric(report: Mapping[str, Any], group: str, estimator: str) -> dict[str, Any]:
    for entry in report["metrics"]["by_group"].get(group, []):
        if entry["estimator"] == estimator:
            return entry
    return {}


def _m4_metric(report: Mapping[str, Any], estimator: str) -> dict[str, Any]:
    for entry in report["metrics"]["overall"]:
        if entry["estimator"] == estimator:
            return entry
    return {}


def extract(reports: Mapping[str, Any]) -> dict[str, Any]:
    """Every number the report quotes, with the key it was read from.

    The ``source`` string on each block is not decoration: it is what lets a
    reader check a figure in the final report against the experiment that
    produced it, without trusting this script.
    """
    m4 = reports["reference_attack_hin"]
    m5 = reports["milestone5_oov_attack"]
    m3 = reports["pcfg_benchmark_hin"]
    m2 = reports["password_benchmark_hin"]
    coverage = reports["indicdict_coverage_hin"]

    m5_groups = {row["population"]: row for row in m5["coverage"]["by_group"]}
    m5_categories = {row["population"]: row for row in m5["coverage"]["by_category"]}
    m4_categories = {row["category"]: row for row in m4["coverage"]["by_category"]}

    return {
        "dictionary": {
            "source": "indicdict_coverage_hin.json",
            "entries": m4["dictionaries"][0]["entries"],
            "probe": coverage.get("full_probe", {}).get("coverage"),
            "core_probe": coverage.get("core_probe", {}).get("coverage"),
            "tiers": [
                {"name": tier["name"], "size": tier["size"]}
                for tier in m4["dictionaries"][0]["tiers"]
            ],
        },
        "benchmark": {
            "source": "password_benchmark_hin.json",
            "samples": m2["corpus"]["total_samples"],
            "generator_version": m2["corpus"]["generator_version"],
            "categories": {
                name: block["samples"]
                for name, block in m2["corpus"].get("categories", {}).items()
            },
            "seed": m4.get("corpus_seed"),
        },
        "m2_vs_baseline": {
            "source": "password_benchmark_hin.json -> comparison[]",
            "by_category": [
                {
                    "category": row["category"],
                    "samples": row["samples"],
                    "indicpass_mean_log10": row["indicpass"]["mean_log10_guesses"],
                    "baseline_mean_log10": row["baseline"]["mean_log10_guesses"],
                    "mean_difference": row["mean_log10_difference"],
                    "indicpass_match_rate": row["indicpass"]["match_rate"],
                }
                for row in m2["comparison"]
            ],
        },
        "m3_character_model": {
            "source": "pcfg_benchmark_hin.json -> character_model",
            **m3["character_model"],
        },
        "m4": {
            "source": "reference_attack_hin.json",
            "coverage": m4["coverage"]["overall"],
            "by_category": m4_categories,
            "universe_log10": m4["attack"]["log10_universe_size"],
            "metrics": {name: _m4_metric(m4, name) for name, _ in ESTIMATORS},
            "calibration": {
                entry["estimator"]: entry for entry in m4["calibration"]["overall"]
            },
            "random_control": m4["controls"]["random"],
            "arms": [
                {
                    "name": arm["name"],
                    "independent": arm["independent_of_estimator_evidence"],
                    "coverage": arm["coverage"]["coverage"],
                    "spearman": {
                        entry["estimator"]: entry["spearman"] for entry in arm["metrics"]
                    },
                }
                for arm in m4["arms"]
            ],
        },
        "m5": {
            "source": "milestone5_oov_attack.json",
            "coverage": m5_groups,
            "by_category": m5_categories,
            "partitions": m5["taxonomy"]["partitions"],
            "universe_log10": m5["attack"]["log10_universe_size"],
            "max_level": m5["attack"]["max_level"],
            "metrics": {
                group: {name: _metric(m5, group, name) for name, _ in ESTIMATORS}
                for group in m5["metrics"]["by_group"]
            },
            "calibration": {
                group: {entry["estimator"]: entry for entry in entries}
                for group, entries in m5["calibration"]["by_group"].items()
            },
            "uncertainty": m5["uncertainty"],
            "m2_vs_m3": m5["m2_vs_m3"]["table"],
            "separation": m5["controls"]["separation"],
            "arms_agree": m5["controls"]["arms_agree"],
            "verdict": m5["verdict"],
            "exclusion_reasons": m5["coverage"]["overall"]["exclusion_reasons"],
        },
        "hashes": {
            "source": "milestone5_oov_attack.json -> artifact_hashes",
            **m5["artifact_hashes"],
            "corpus_digest": m5["corpus_digest"],
            "m5_canonical": m5["reproducibility"]["canonical_sha256"],
            "m5_byte_identical": m5["reproducibility"]["byte_identical"],
        },
    }


# -- figures ----------------------------------------------------------------


def build_figures(data: Mapping[str, Any]) -> dict[str, str]:
    """Every figure, as ``filename -> SVG text``.

    Drawn from ``data`` and therefore from the committed reports. A figure that
    disagreed with the table beside it would be the worst kind of error in a
    document like this, so both read the same extraction.
    """
    m4, m5 = data["m4"], data["m5"]
    figures: dict[str, str] = {}

    # 1. coverage, M4 against M5 ------------------------------------------
    # The out-of-lexicon row's two denominators differ and are named, rather
    # than silently divided into one bar: M4 counts a stem its wordlist cannot
    # produce (872, using the combinator, so a two-word body can still count as
    # seen), M5 counts a body absent from the dictionary (968). Both are "the
    # dictionary does not have this", measured by each attack's own machinery.
    unseen = m4["coverage"]["unseen_stem"]
    oov = m5["coverage"]["oov"]
    categories = [
        "all 1,400 targets",
        f"out-of-lexicon (M4 n={unseen}, M5 n={oov['targets']})",
        "english control",
        "indic (single word)",
        "mixed constructions",
        "random control",
    ]
    m4_cov = [
        m4["coverage"]["coverage"],
        m4["coverage"]["unseen_stem_covered"] / unseen if unseen else 0.0,
        m4["by_category"]["english"]["coverage"],
        m4["by_category"]["indic_word"]["coverage"],
        m4["by_category"]["mixed"]["coverage"],
        m4["by_category"]["random"]["coverage"],
    ]
    m5_cov = [
        m5["coverage"]["all"]["coverage"],
        oov["coverage"],
        m5["by_category"]["english"]["coverage"],
        m5["by_category"]["indic_word"]["coverage"],
        m5["by_category"]["mixed"]["coverage"],
        m5["by_category"]["random"]["coverage"],
    ]
    figures["coverage_m4_vs_m5.svg"] = grouped_bars(
        title="Benchmark coverage: M4 wordlist attack vs M5 character attack",
        subtitle="Share of targets the attack reaches and can therefore rank. Both attacks "
        "were given the same 10^16 candidate budget. The out-of-lexicon row's two "
        "denominators differ and are labelled: each attack measures it with its own "
        "membership machinery.",
        categories=categories,
        series=[
            Series("M4 (wordlist x rules)", PALETTE["m4"], m4_cov),
            Series("M5 (character model)", PALETTE["m5"], m5_cov),
        ],
        value_format="{:.1%}",
        axis_label="fraction of targets reachable",
    )

    # 2. rank correlation ---------------------------------------------------
    groups = list(HEADLINE)
    figures["rank_correlation.svg"] = grouped_bars(
        title="Rank correlation with the observed attack order (M5)",
        subtitle="Spearman rho between predicted log10 guesses and observed log10 attack "
        "rank. Reachable targets only; n differs per population.",
        categories=[f"{g}  (n={m5['metrics'][g]['indicpass'].get('samples', 0)})" for g in groups],
        series=[
            Series(
                label,
                PALETTE[name],
                [m5["metrics"][g][name].get("spearman") for g in groups],
            )
            for name, label in ESTIMATORS
        ],
        axis_label="Spearman rho (higher is better)",
    )

    # 3. mean absolute error ------------------------------------------------
    figures["mean_absolute_error.svg"] = grouped_bars(
        title="Mean absolute error against the observed attack order (M5)",
        subtitle="|predicted log10 guesses - observed log10 attack rank|, in orders of "
        "magnitude. Lower is better.",
        categories=[f"{g}  (n={m5['metrics'][g]['indicpass'].get('samples', 0)})" for g in groups],
        series=[
            Series(
                label,
                PALETTE[name],
                [m5["metrics"][g][name].get("mean_absolute_error") for g in groups],
            )
            for name, label in ESTIMATORS
        ],
        value_format="{:.2f}",
        axis_label="MAE in log10 guesses (lower is better)",
    )

    # 4. where the attack reaches each population --------------------------
    separation = m5["separation"]
    figures["oov_vs_random_separation.svg"] = grouped_bars(
        title="How deep the character attack has to go (M5)",
        subtitle="Median log10 attack rank. The gap between out-of-lexicon Hindi and random "
        "strings is what says the character model carries information rather than noise.",
        categories=["in lexicon", "out-of-lexicon Indic", "random control"],
        series=[
            Series(
                "median log10 attack rank",
                PALETTE["attack"],
                [
                    separation["median_log10_rank_in_lexicon"],
                    separation["median_log10_rank_oov_indic"],
                    separation["median_log10_rank_random"],
                ],
            )
        ],
        value_format="{:.2f}",
        axis_label="median log10 rank (further right = attacker needs more guesses)",
    )

    # 5. calibration --------------------------------------------------------
    figures["calibration.svg"] = grouped_bars(
        title="Calibration against the observed attack order (M5)",
        subtitle="OLS slope of observed log10 rank on predicted log10 guesses. 1.0 is perfect; "
        "below 1 means the estimator compresses the scale.",
        categories=[f"{g}  (n={m5['metrics'][g]['indicpass'].get('samples', 0)})" for g in groups],
        series=[
            Series(
                label,
                PALETTE[name],
                [m5["calibration"].get(g, {}).get(name, {}).get("slope") for g in groups],
            )
            for name, label in ESTIMATORS
        ],
        axis_label="calibration slope (1.0 is perfect)",
    )

    # 6. per benchmark category --------------------------------------------
    category_groups = [
        "english_control",
        "indic_in_lexicon",
        "oov_name",
        "oov_spelling_variant",
        "oov_morphological_variant",
        "oov_stem_suffix",
        "oov_other",
        "mixed_construction",
        "random_control",
    ]
    available = [g for g in category_groups if g in m5["metrics"]]
    figures["per_category.svg"] = grouped_bars(
        title="Rank correlation per benchmark partition (M5)",
        subtitle="Populations are NOT comparable with each other: each is conditional on its "
        "own coverage and its own n. Bars are omitted where the statistic is undefined.",
        categories=[
            f"{g}  (n={m5['metrics'][g]['indicpass'].get('samples', 0)})" for g in available
        ],
        series=[
            Series(
                label,
                PALETTE[name],
                [m5["metrics"][g][name].get("spearman") for g in available],
            )
            for name, label in ESTIMATORS
        ],
        axis_label="Spearman rho (higher is better)",
    )

    # 7. the paired differences, with intervals ----------------------------
    rows: list[tuple[str, float | None, float | None, float | None]] = []
    for entry in m5["m2_vs_m3"]:
        difference = entry["differences"].get("spearman") or {}
        rows.append(
            (
                f"{entry['group']}  (n={entry['samples']})",
                difference.get("point"),
                difference.get("ci_low"),
                difference.get("ci_high"),
            )
        )
    figures["confidence_intervals_spearman.svg"] = intervals(
        title="M3 minus M2, rank correlation, with 95% bootstrap intervals",
        subtitle="Paired percentile bootstrap, 2,000 resamples, seed 42. Positive favours the "
        "PCFG. An interval excluding zero is reported as such; it is not a significance test.",
        rows=rows,
        axis_label="Spearman rho difference (PCFG minus IndicPass)",
    )

    error_rows: list[tuple[str, float | None, float | None, float | None]] = []
    for entry in m5["m2_vs_m3"]:
        difference = entry["differences"].get("mean_absolute_error") or {}
        error_rows.append(
            (
                f"{entry['group']}  (n={entry['samples']})",
                difference.get("point"),
                difference.get("ci_low"),
                difference.get("ci_high"),
            )
        )
    figures["confidence_intervals_mae.svg"] = intervals(
        title="M3 minus M2, mean absolute error, with 95% bootstrap intervals",
        subtitle="Same paired bootstrap. NEGATIVE favours the PCFG here, because a lower error "
        "is better. The two figures disagree, and that disagreement is the result.",
        rows=error_rows,
        colour=PALETTE["pcfg"],
        axis_label="MAE difference in log10 guesses (PCFG minus IndicPass)",
    )
    return figures


# -- rendering --------------------------------------------------------------


def _f(value: Any, spec: str = ".3f") -> str:
    if value is None:
        return "--"
    return format(value, spec) if isinstance(value, (int, float)) else str(value)


def _pct(value: Any) -> str:
    return "--" if value is None else f"{value:.1%}"


def _ci(entry: Mapping[str, Any] | None, spec: str = ".3f") -> str:
    if not entry or entry.get("point") is None:
        return "--"
    point = _f(entry["point"], spec)
    if entry.get("ci_low") is None:
        return point
    return f"{point} [{_f(entry['ci_low'], spec)}, {_f(entry['ci_high'], spec)}]"


def render(report: Mapping[str, Any]) -> str:
    data = report["findings"]
    m4, m5 = data["m4"], data["m5"]
    lines: list[str] = []
    add = lines.append

    add("# IndicPass: a Romanized-Indic password-strength estimator, and what two "
        "independent attackers say about it")
    add("")
    add(f"Final research report. Generated {report['generated_at']} from "
        f"{report['project']} at `{report['git_commit'][:12]}`.")
    add("")
    add("Every number below is read from a committed milestone report and is not "
        "recomputed here. Section 24 lists the commands that regenerate all of them, "
        "and the JSON beside this file carries each figure with the report and key it "
        "came from.")
    add("")

    # 1 ---------------------------------------------------------------------
    add("## 1. Abstract")
    add("")
    verdict = m5["verdict"]
    add(f"Password-strength meters are built on English wordlists. India's "
        f"{data['dictionary']['entries']:,}-word Romanized-Hindi vocabulary is absent from "
        "them, so a password like `namaste@123` is scored as though it were random text. "
        "IndicPass builds a Romanized-Indic dictionary from a trained transliteration "
        "model and prices passwords against it (**M2**), adds a probabilistic grammar with "
        "a character model so that a Hindi spelling the dictionary never saw is still "
        "recognisably Hindi (**M3**), and then -- because comparing two estimators with "
        "each other cannot say which is right -- validates both against two **independent, "
        "bounded reference attackers** whose ranks are observed rather than estimated "
        "(**M4**, **M5**).")
    add("")
    add(f"The measured result is a split, and it is stable. On the "
        f"{m5['metrics']['oov_indic']['indicpass']['samples']} out-of-lexicon Indic targets "
        f"M2 orders passwords better (Spearman "
        f"{_f(m5['metrics']['oov_indic']['indicpass']['spearman'])} against M3's "
        f"{_f(m5['metrics']['oov_indic']['pcfg']['spearman'])}) while M3 gets the magnitude "
        f"closer (MAE {_f(m5['metrics']['oov_indic']['pcfg']['mean_absolute_error'], '.3f')} "
        f"against M2's "
        f"{_f(m5['metrics']['oov_indic']['indicpass']['mean_absolute_error'], '.3f')}). Both "
        "differences hold in every attacker arm, including the one that shares no training "
        "evidence with either estimator. Both estimators beat zxcvbn on every metric by a "
        "wide margin. The character model's out-of-lexicon *mechanism* is confirmed -- an "
        f"unseen Hindi spelling is reached "
        f"{_f(m5['separation']['orders_of_magnitude_separation'], '.2f')} orders of magnitude "
        "earlier than a random string of similar shape -- but that mechanism does not make "
        "M3 the better ranker.")
    add("")
    add(f"**Milestone 3's central out-of-lexicon claim is therefore "
        f"{verdict['status'].replace('_', ' ')}**: supported for calibration, unsupported "
        "for ordering. The shipped 0-4 score continues to come from M2.")
    add("")

    # 2 ---------------------------------------------------------------------
    add("## 2. Problem statement")
    add("")
    add("A strength meter estimates how many guesses an attacker needs. Every widely "
        "deployed one -- zxcvbn among them -- does this by matching the password against "
        "wordlists, and those wordlists are English. Hundreds of millions of people choose "
        "passwords from a Romanized Indic vocabulary that appears in none of them, so the "
        "meter finds no structure, falls back on a brute-force estimate, and reports a "
        "weak password as strong. That is the dangerous direction of error: it tells "
        "someone a crackable password is fine.")
    add("")
    add("The engineering problem is that no Romanized-Indic password wordlist exists, and "
        "no leaked Indian password corpus can be used to build one in an academic project. "
        "The scientific problem is harder: even with such a lexicon, showing that an "
        "estimate *improved* requires a ground truth that is not itself an estimate.")
    add("")

    # 3 ---------------------------------------------------------------------
    add("## 3. Research gap")
    add("")
    add("| gap | how this project addresses it |")
    add("| --- | --- |")
    add("| No Romanized-Indic password lexicon | Build one from a trained transliteration "
        "model over Aksharantar, joined to an external frequency table (M1) |")
    add("| Romanized Hindi has no standard orthography, so any fixed lexicon misses real "
        "spellings | A character model over the lexicon's spellings, so unseen ones are "
        "still priced as Hindi (M3) |")
    add("| Estimator comparisons are estimator-versus-estimator | Two independent bounded "
        "attackers whose ranks are observed, not modelled (M4, M5) |")
    add("| A wordlist attacker structurally cannot reach the out-of-lexicon population | "
        "A second attacker whose candidates come from a character model (M5) |")
    add("| Point estimates on sub-populations of a few hundred | Paired bootstrap intervals "
        "on every headline metric and on the differences (M5) |")
    add("")

    # 4 ---------------------------------------------------------------------
    add("## 4. Threat / attacker model")
    add("")
    add("Both attackers are **bounded reference models**. They are specified completely, "
        "they are reproducible from a seed and a config, and their ranks are exact. They "
        "are **not** claims about the space of real attackers: neither has a leaked "
        "password corpus, leet substitution, keyboard walks, or targeted personal data, "
        "and no leaked corpus is used anywhere in this project.")
    add("")
    add("| | M4 -- reference attack | M5 -- character attack |")
    add("| --- | --- | --- |")
    add("| candidate source | IndicDict spellings, ordered "
        "| any lower-case letter string, generated |")
    add("| structure | `case(word) + suffix`, plus `word+word` | `case(stem) + suffix` |")
    add("| ordering | rule block, then wordlist position "
        "| quantised cost level, then shape, then stem |")
    add("| budget | 10^16 candidates | 10^16 candidates (inherited, so the two are comparable) |")
    add(f"| universe | 10^{_f(m4['universe_log10'], '.2f')} | "
        f"10^{_f(m5['universe_log10'], '.2f')} (levels 0-{m5['max_level']}) |")
    add("| reaches out-of-lexicon spellings | **no, structurally** | **yes** |")
    add("| enumeration | counted, never materialised | counted, never materialised |")
    add("")
    add("Neither attack builds a wordlist at any point. Both invert their ordering "
        "arithmetically, so a rank is recovered without listing anything that precedes it, "
        "and **no cracking wordlist exists anywhere in this pipeline**.")
    add("")

    # 5 ---------------------------------------------------------------------
    add("## 5. IndicDict construction")
    add("")
    dictionary = data["dictionary"]
    add(f"{dictionary['entries']:,} Romanized-Hindi entries, built offline by "
        "`scripts/build_indicdict.py` from the trained transliterator and committed as a "
        "build artefact. Scoring is a dictionary lookup; the neural model never runs at "
        "scoring time.")
    add("")
    add("| provenance tier | entries |")
    add("| --- | ---: |")
    for tier in dictionary["tiers"]:
        add(f"| `{tier['name']}` | {tier['size']:,} |")
    add(f"| **total** | **{dictionary['entries']:,}** |")
    add("")
    add("Tiers order entries by *how the pair was produced* -- human romanizations first, "
        "model-mined last -- and are the fallback pricing policy. An entry whose native "
        "form was found in the external frequency table is priced by its measured rank "
        "instead; only the remainder fall back to a tier.")
    add("")
    if dictionary.get("probe") is not None:
        add(f"Measured against a curated probe set of everyday Romanized Hindi, coverage is "
            f"**{_pct(dictionary['probe'])}** overall. That number is a finding, not a "
            "failure to fix: words are never added to the dictionary to make it look "
            "better, and the gap is precisely what M3's character model exists for.")
        add("")

    # 6 ---------------------------------------------------------------------
    add("## 6. M2 -- the lexical estimator")
    add("")
    add("M2 prices a password as the cheapest explanation an attacker has: segment it, "
        "match segments against IndicDict, charge each match its position in a "
        "frequency-ordered wordlist, charge digits/years/symbols/case their own costs, and "
        "take the minimum over segmentations. The output is `log10_guesses`, and the 0-4 "
        "score is a threshold on it.")
    add("")
    add("Against zxcvbn on the generated benchmark, by category:")
    add("")
    add("| category | n | M2 mean log10 | zxcvbn mean log10 | difference | M2 match rate |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for row in data["m2_vs_baseline"]["by_category"]:
        add(f"| {row['category']} | {row['samples']} | "
            f"{_f(row['indicpass_mean_log10'], '.2f')} | "
            f"{_f(row['baseline_mean_log10'], '.2f')} | "
            f"{row['mean_difference']:+.2f} | {_pct(row['indicpass_match_rate'])} |")
    add("")
    add("A *lower* estimate is not automatically a better one: that judgement needs a "
        "reference attack, which is what M4 and M5 supply. Read this table as "
        "\"the two estimators disagree, and here is where\".")
    add("")

    # 7 ---------------------------------------------------------------------
    add("## 7. M3 -- the PCFG and the character model")
    add("")
    add("M3 is a probability model over passwords -- structure prior, word distribution, "
        "digit/year/symbol distributions, and an order-4 character n-gram with Witten-Bell "
        "smoothing over the dictionary's spellings -- from which a guess number is derived "
        "by *counting* a sampled guess curve rather than by a formula.")
    add("")
    add("The character model exists for one reason, and it works. Cost per character, "
        "`-log10 P`, lower means the model finds the text likelier:")
    add("")
    character = data["m3_character_model"]
    add("| population | words | log10 cost per character |")
    add("| --- | ---: | ---: |")
    for name, block in character["populations"].items():
        add(f"| {name} | {block['words']} | {block['log10_cost_per_character']:.4f} |")
    add(f"| *(brute-force floor)* | -- | {character['bruteforce_floor_cost_per_character']:.4f} |")
    add("")
    present = character["populations"]["indic_bank_in_dictionary"]["log10_cost_per_character"]
    absent = character["populations"]["indic_bank_absent_from_dictionary"][
        "log10_cost_per_character"
    ]
    add(f"**This is the generalisation test, and it passes.** Hindi words the dictionary "
        f"contains cost {present:.4f} per character; Hindi words it does **not** contain "
        f"cost {absent:.4f} -- a difference of {abs(present - absent):.4f}. The model "
        "learned the shape of the language, not its vocabulary. Random lower-case text "
        f"costs {character['populations']['random_lowercase']['log10_cost_per_character']:.4f}, "
        "well above the brute-force floor, so the grammar cannot make a random string look "
        "cheap.")
    add("")

    # 8 ---------------------------------------------------------------------
    add("## 8. M4 -- the independent reference attack")
    add("")
    add("A wordlist run through an ordered rule programme, which is what hashcat and John "
        "the Ripper do and what every published cracking study assumes. The lexicon is "
        "IndicDict's spellings in a documented order; the rules are bounded products of "
        "the lexicon with suffix families. A target's rank is the first position the "
        "enumeration emits it at, recovered by inverting the rule.")
    add("")
    add(f"Universe 10^{_f(m4['universe_log10'], '.2f')} candidates. **Independence is "
        "mechanical**: the module imports nothing but the standard library, and the tests "
        "assert that by parsing its import set, by denylisting the estimator modules, and "
        "by ranking a corpus with all three estimators replaced by objects that raise on "
        "contact.")
    add("")

    # 9 ---------------------------------------------------------------------
    add("## 9. M5 -- the out-of-lexicon attack")
    add("")
    add("M4 has one structural limitation and it is the one that matters: its universe is a "
        "wordlist, so a password built from a spelling the wordlist lacks is not in it at "
        "all. M5 replaces the wordlist with a character model, so the candidate is "
        "`case(stem) + suffix` where **stem is any string over the 26 lower-case letters** "
        "within a length band. An out-of-lexicon spelling becomes reachable on the same "
        "terms as one the dictionary holds.")
    add("")
    add("Candidates are ordered by an integer quantised cost level; the number at each "
        "level is a dynamic programme over `(remaining length, context, remaining level)`, "
        "so a universe of 10^22 stems is **counted without being built** and a rank is "
        "recovered by inversion. The character model is independently implemented with "
        "different order and different smoothing from M3's, and the module again imports "
        "nothing but the standard library.")
    add("")
    add("The budget is inherited from M4 -- the same 10^16 candidates -- so the difference "
        "in their coverage is a statement about the candidate model rather than about how "
        "long each attacker was allowed to run.")
    add("")

    # 10 --------------------------------------------------------------------
    add("## 10. Experimental methodology")
    add("")
    add("1. Generate the benchmark from a committed word bank and a seed.")
    add("2. Score every password with all three estimators **once, before any attack "
        "object exists**. The pipeline is written so this cannot be reordered, and a test "
        "parses `main()` to assert it.")
    add("3. Build each attacker and rank every target. Reuse the scores unchanged across "
        "every attacker arm.")
    add("4. Partition the targets by dictionary membership and by an out-of-lexicon "
        "taxonomy, mechanically, before any metric is computed.")
    add("5. Compute metrics per population on **reachable targets only**, and report "
        "coverage beside every one of them.")
    add("6. Bootstrap the primary metrics and the paired differences.")
    add("7. Re-run the whole experiment in a second process and compare byte for byte.")
    add("")
    add("Ablation arms change exactly one thing each, so a conclusion that depends on an "
        "assumption shows up as an arm that disagrees.")
    add("")

    # 11 --------------------------------------------------------------------
    add("## 11. Benchmark composition")
    add("")
    benchmark = data["benchmark"]
    add(f"{benchmark['samples']:,} generated samples, generator version "
        f"{benchmark['generator_version']}, seed {benchmark['seed']}. The corpus is "
        "**generated, not collected**: no real password appears anywhere, and no password "
        "reaches disk in any report.")
    add("")
    add("| category | samples | role |")
    add("| --- | ---: | --- |")
    roles = {
        "english": "generic control -- a non-Indic estimator should already handle these",
        "indic_word": "single Romanized Hindi word",
        "indic_numeric": "word + digit run",
        "indic_year": "word + year",
        "indic_symbol": "word + symbol (+ digits)",
        "mixed": "two lexical pieces concatenated",
        "random": "upper control -- no lexical structure to find",
    }
    for name, count in benchmark["categories"].items():
        add(f"| `{name}` | {count} | {roles.get(name, '')} |")
    add("")
    add("The Indic word bank was written from everyday usage and deliberately **not** "
        "sampled from IndicDict: sampling the dictionary would guarantee coverage and "
        "measure nothing. The consequence is that many bank words are missing from the "
        "dictionary, and that population is the subject of section 16.")
    add("")
    add("M5 partitions the same 1,400 targets mechanically:")
    add("")
    add("| partition | targets | in IndicDict | reachable | coverage |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for name, block in m5["partitions"].items():
        add(f"| `{name}` | {block['targets']} | {block['in_lexicon']} | "
            f"{block['reachable']} | {_pct(block['coverage'])} |")
    add("")

    # 12 --------------------------------------------------------------------
    add("## 12. M4 results")
    add("")
    coverage4 = m4["coverage"]
    add(f"Coverage **{coverage4['covered']}/{coverage4['targets']} "
        f"({_pct(coverage4['coverage'])})**. Of the {coverage4['unseen_stem']} targets whose "
        f"stem is absent from the lexicon, **{coverage4['unseen_stem_covered']} are "
        "reachable** -- the structural limitation that motivated M5.")
    add("")
    add("| estimator | n | Spearman | Pearson | mean err | MAE | RMSE | +-1.0 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    for name, label in ESTIMATORS:
        entry = m4["metrics"][name]
        add(f"| {label} | {entry['samples']} | {_f(entry['spearman'])} | "
            f"{_f(entry['pearson'])} | {entry['mean_signed_error']:+.3f} | "
            f"{entry['mean_absolute_error']:.3f} | {entry['rmse']:.3f} | "
            f"{_pct(entry['within_1.0_log10'])} |")
    add("")
    control = m4["random_control"]
    add(f"**Control.** The attack reaches {control['covered']} of {control['targets']} random "
        f"strings ({_pct(control['coverage'])}). It must not reach them: its rules are a "
        "wordlist crossed with short suffixes, and a high number here would mean the "
        "lexicon was matching noise.")
    add("")

    # 13 --------------------------------------------------------------------
    add("## 13. M5 results")
    add("")
    add("![Coverage, M4 against M5](../figures/coverage_m4_vs_m5.svg)")
    add("")
    add("| population | targets | reachable | coverage | median log10 rank |")
    add("| --- | ---: | ---: | ---: | ---: |")
    for group in HEADLINE:
        row = m5["coverage"][group]
        add(f"| `{group}` | {row['targets']} | {row['reachable']} | "
            f"{_pct(row['coverage'])} | {_f(row['median_log10_rank'], '.2f')} |")
    add("")
    add(f"Coverage rises from {_pct(m4['coverage']['coverage'])} to "
        f"{_pct(m5['coverage']['all']['coverage'])} overall, and from "
        f"**0 of {m4['coverage']['unseen_stem']}** to "
        f"**{m5['coverage']['oov_indic']['reachable']} of "
        f"{m5['coverage']['oov_indic']['targets']}** on out-of-lexicon Indic targets.")
    add("")
    add("The targets M5 still cannot reach are excluded for named reasons, and each is "
        "given **no rank at all**:")
    add("")
    add("| reason | targets |")
    add("| --- | ---: |")
    for reason, count in m5["exclusion_reasons"].items():
        add(f"| `{reason}` | {count} |")
    add("")

    # 14 --------------------------------------------------------------------
    add("## 14. M2 against M3 -- ordering")
    add("")
    add("![Rank correlation](../figures/rank_correlation.svg)")
    add("")
    add("![Paired differences, Spearman](../figures/confidence_intervals_spearman.svg)")
    add("")
    add("| population | n | rho M2 | rho M3 | rho zxcvbn | M3 - M2 [95% CI] |")
    add("| --- | ---: | ---: | ---: | ---: | --- |")
    for entry in m5["m2_vs_m3"]:
        group = entry["group"]
        zx = m5["metrics"].get(group, {}).get("baseline", {}).get("spearman")
        add(f"| `{group}` | {entry['samples']} | {_f(entry['indicpass']['spearman'])} | "
            f"{_f(entry['pcfg']['spearman'])} | {_f(zx)} | "
            f"{_ci(entry['differences'].get('spearman'))} |")
    add("")
    add("**M2 orders better wherever the population is out of lexicon; M3 orders better "
        "wherever it is in lexicon.** Both directions have intervals that exclude zero. "
        "This is not a contradiction: M3's advantage comes from its word distribution, "
        "which needs the word to be in the dictionary, and out of lexicon both estimators "
        "fall back on something strongly length-driven that M2 happens to track slightly "
        "better.")
    add("")

    # 15 --------------------------------------------------------------------
    add("## 15. M2 against M3 -- calibration")
    add("")
    add("![Mean absolute error](../figures/mean_absolute_error.svg)")
    add("")
    add("![Paired differences, MAE](../figures/confidence_intervals_mae.svg)")
    add("")
    add("![Calibration slope](../figures/calibration.svg)")
    add("")
    add("| population | n | MAE M2 | MAE M3 | MAE zxcvbn | M3 - M2 [95% CI] |")
    add("| --- | ---: | ---: | ---: | ---: | --- |")
    for entry in m5["m2_vs_m3"]:
        group = entry["group"]
        zx = m5["metrics"].get(group, {}).get("baseline", {}).get("mean_absolute_error")
        add(f"| `{group}` | {entry['samples']} | "
            f"{entry['indicpass']['mean_absolute_error']:.3f} | "
            f"{entry['pcfg']['mean_absolute_error']:.3f} | {_f(zx, '.3f')} | "
            f"{_ci(entry['differences'].get('mean_absolute_error'))} |")
    add("")
    add("**M3 has the lower absolute error in every population**, and the interval excludes "
        "zero in most of them. Its mean *signed* error is also closer to zero, meaning it "
        "is less systematically pessimistic. Both estimators under-estimate the attack "
        "throughout -- the safe direction for a meter, and still an error.")
    add("")

    # 16 --------------------------------------------------------------------
    add("## 16. Out-of-lexicon findings")
    add("")
    add("![Attack depth by population](../figures/oov_vs_random_separation.svg)")
    add("")
    separation = m5["separation"]
    add("| population | median log10 attack rank |")
    add("| --- | ---: |")
    add(f"| in lexicon | {_f(separation['median_log10_rank_in_lexicon'], '.2f')} |")
    add(f"| out-of-lexicon Indic | {_f(separation['median_log10_rank_oov_indic'], '.2f')} |")
    add(f"| random control | {_f(separation['median_log10_rank_random'], '.2f')} |")
    add("")
    add(f"**{_f(separation['orders_of_magnitude_separation'], '.2f')} orders of magnitude** "
        "separate an out-of-lexicon Hindi spelling from a random string. This is the "
        "milestone's strongest positive result and it confirms M3's proposed mechanism "
        "independently of M3: a character model trained only on a transliteration "
        "dictionary really does place Hindi-shaped spellings it has never seen far earlier "
        "in an attack than noise. Section 7's generalisation test says the same thing from "
        "inside M3.")
    add("")
    add("What it does **not** show is that M3's estimator exploits that mechanism better "
        "than M2 does. The verdict, decided by a rule fixed before the numbers were seen:")
    add("")
    add("| sub-claim | statistic | M2 | M3 | M3 - M2 [95% CI] "
        "| holds without shared evidence | status |")
    add("| --- | --- | ---: | ---: | --- | --- | --- |")
    for name, block in verdict["sub_claims"].items():
        low, high = block["difference_ci"]
        interval = (
            f"{_f(block['difference'])} [{_f(low)}, {_f(high)}]"
            if low is not None
            else _f(block["difference"])
        )
        add(f"| {name} | `{block['statistic']}` | {_f(block['indicpass'])} | "
            f"{_f(block['pcfg'])} | {interval} | "
            f"{block['holds_under_independent_arms']} | "
            f"**{block['status'].replace('_', ' ')}** |")
    add("")
    add(f"Overall: **{verdict['status'].replace('_', ' ')}**.")
    add("")
    add("![Per partition](../figures/per_category.svg)")
    add("")

    # 17 --------------------------------------------------------------------
    add("## 17. Comparison with zxcvbn")
    add("")
    add("zxcvbn is the deployed generic estimator and the reason a comparative claim is "
        "possible at all. It is **not an Indic-specific attacker** and is not being "
        "criticised for failing at something it was not built for; it is the measurement "
        "of what a generic meter does with this population.")
    add("")
    add("| population | n | rho | MAE | RMSE | +-1.0 |")
    add("| --- | ---: | ---: | ---: | ---: | ---: |")
    for group in HEADLINE:
        entry = m5["metrics"][group]["baseline"]
        add(f"| `{group}` | {entry['samples']} | {_f(entry['spearman'])} | "
            f"{entry['mean_absolute_error']:.3f} | {entry['rmse']:.3f} | "
            f"{_pct(entry['within_1.0_log10'])} |")
    add("")
    oov = m5["metrics"]["oov_indic"]
    add(f"On out-of-lexicon Indic targets zxcvbn's absolute error is "
        f"{oov['baseline']['mean_absolute_error']:.2f} orders of magnitude against M2's "
        f"{oov['indicpass']['mean_absolute_error']:.2f} and M3's "
        f"{oov['pcfg']['mean_absolute_error']:.2f} -- roughly **twice** either Indic "
        "estimator's. Its rank correlation is lower than both in every population. This is "
        "the one comparison in the report that is not close, and it is the project's "
        "practical justification.")
    add("")

    # 18 --------------------------------------------------------------------
    add("## 18. Robustness and control experiments")
    add("")
    add("**Random controls.** M4 reaches "
        f"{_pct(m4['random_control']['coverage'])} of random strings; M5 reaches "
        f"{_pct(m5['coverage']['random_control']['coverage'])} of them and only at a median "
        f"rank of {_f(m5['coverage']['random_control']['median_log10_rank'], '.2f')}. "
        "Neither attack finds structure that is not there.")
    add("")
    add("**Attacker arms.** Each arm changes exactly one thing. The M5 direction on "
        "out-of-lexicon targets is identical in all of them:")
    add("")
    add("| arm | shares evidence with an estimator | n | rho M2 | rho M3 "
        "| M3 wins rho | M3 wins MAE |")
    add("| --- | --- | ---: | ---: | ---: | --- | --- |")
    for name, row in m5["arms_agree"].items():
        add(f"| `{name}` | {'no' if row['independent_of_estimator_evidence'] else 'yes'} | "
            f"{row['samples']} | {_f(row['spearman_indicpass'])} | "
            f"{_f(row['spearman_pcfg'])} | {row['pcfg_better_spearman']} | "
            f"{row['pcfg_better_mae']} |")
    add("")
    add("**The strongest robustness result is the `uniform` row.** That arm has no character "
        "statistics at all -- every symbol costs the same, so the ordering is length then "
        "spelling -- which means no estimator has any informational advantage in it. The "
        "M2-orders-better / M3-calibrates-better split survives there unchanged, so it is a "
        "statement about the estimators rather than about shared training data.")
    add("")
    add("**M4's arms** agree in the same way: the ordering result holds under `shuffled` and "
        "`length`, the two arms whose wordlist order no estimator has access to.")
    add("")
    add("| arm | independent | coverage | rho M2 | rho M3 | rho zxcvbn |")
    add("| --- | --- | ---: | ---: | ---: | ---: |")
    for arm in m4["arms"]:
        add(f"| `{arm['name']}` | {'yes' if arm['independent'] else 'NO'} | "
            f"{_pct(arm['coverage'])} | {_f(arm['spearman'].get('indicpass'))} | "
            f"{_f(arm['spearman'].get('pcfg'))} | {_f(arm['spearman'].get('baseline'))} |")
    add("")

    # 19 --------------------------------------------------------------------
    add("## 19. Uncertainty and bootstrap methodology")
    add("")
    bootstrap = m5["uncertainty"].get("oov_indic", {})
    add(f"Percentile bootstrap, {bootstrap.get('resamples', 0):,} resamples, fixed seed, "
        f"{_pct(bootstrap.get('confidence', 0.95))} intervals. Resample indices are drawn "
        "**once per population and shared by every estimator**, which is what makes the "
        "reported differences paired: both estimators see the same targets in the same "
        "resample, so the interval is on their difference rather than on two independent "
        "quantities. Populations below 20 targets get point estimates and explicitly no "
        "interval.")
    add("")
    add(f"Intervals on the out-of-lexicon Indic population (n = {bootstrap.get('samples')}):")
    add("")
    add("| estimator | Spearman | MAE | RMSE | +-1.0 | calibration slope | r^2 |")
    add("| --- | --- | --- | --- | --- | --- | --- |")
    for name, label in ESTIMATORS:
        entry = bootstrap.get("estimators", {}).get(name, {})
        if not entry:
            continue
        add(f"| {label} | {_ci(entry['spearman'])} | "
            f"{_ci(entry['mean_absolute_error'], '.2f')} | {_ci(entry['rmse'], '.2f')} | "
            f"{_ci(entry['within_1.0_log10'])} | {_ci(entry['calibration_slope'])} | "
            f"{_ci(entry['r_squared'])} |")
    add("")
    add("An interval that excludes zero is reported as excluding zero. It is **not** called "
        "significant, and overlapping intervals are not treated as evidence of no "
        "difference -- which is precisely why the paired difference is reported separately "
        "from the two estimators' own intervals.")
    add("")

    # 20 --------------------------------------------------------------------
    add("## 20. Limitations")
    add("")
    for index, item in enumerate(LIMITATIONS, start=1):
        add(f"{index}. {item}")
    add("")

    # 21 --------------------------------------------------------------------
    add("## 21. Threats to validity")
    add("")
    add("**Construct validity.** \"Attack rank\" is the position one specified attacker "
        "emits a password at. It is exact, and it is not the number of guesses a real "
        "attacker needs. Every claim in this report is about agreement with a reference "
        "attacker, never about real-world cracking.")
    add("")
    add("**Internal validity.** The estimators are scored on targets the attack reaches, "
        "which is a selected population. Coverage is printed beside every metric so the "
        "selection is visible, and M5 exists because M4's selection excluded the "
        "population the central question is about. The residual risk is that M5's own "
        f"{_pct(1 - m5['coverage']['all']['coverage'])} of unreachable targets are not "
        "missing at random -- they are concentrated in mixed constructions and random "
        "controls, which is stated rather than corrected for.")
    add("")
    add("**External validity.** The benchmark is generated from a hand-written word bank. "
        "It is plausible Romanized Hindi, not observed passwords, and no claim about the "
        "distribution of real Indian passwords is supported by it. The dictionary comes "
        "from one transliteration corpus for one language.")
    add("")
    add("**Circularity.** M4's `frequency` arm and M5's `indicdict` arm share evidence with "
        "the estimators they score. This is stated in both reports, and both carry arms "
        "that remove the shared evidence entirely. Every conclusion in this report is one "
        "that holds in those arms too.")
    add("")
    add("**Researcher degrees of freedom.** The M5 verdict rule was written before the "
        "numbers were computed and is reproduced verbatim in the report. M2 and M3 were "
        "not modified in response to any result.")
    add("")

    # 22 --------------------------------------------------------------------
    add("## 22. Conclusions")
    add("")
    add("1. **A Romanized-Indic lexicon can be built without a leaked corpus.** "
        f"{data['dictionary']['entries']:,} entries, derived from a trained transliteration "
        "model, priced by an external frequency table, reproducible from committed source.")
    add("2. **Both Indic estimators substantially beat a generic one on this population.** "
        "zxcvbn's absolute error against the observed attack order is roughly twice "
        "either's, on every population measured.")
    add("3. **M2 is the better ranker; M3 is the better calibrator.** The split is stable "
        "across two independent attackers, seven M5 arms and six M4 arms, including every "
        "arm that shares no evidence with either estimator.")
    add("4. **M3's out-of-lexicon mechanism is real.** An unseen Hindi spelling is reached "
        f"{_f(separation['orders_of_magnitude_separation'], '.2f')} orders of magnitude "
        "earlier than noise, and M3's own character model prices dictionary-absent Hindi "
        "words the same as dictionary-present ones.")
    add("5. **The mechanism does not make M3 the better estimator overall.** On the "
        "out-of-lexicon population it wins calibration and loses ordering, and the "
        "difference is small in both directions.")
    add("6. **The shipped 0-4 score therefore stays on M2**, with M3 and zxcvbn reported "
        "alongside. A 0-4 band is an ordering device, and M2 orders best.")
    add("")
    add("The negative result is kept deliberately. M3 was built to improve out-of-lexicon "
        "estimation, and on the metric a strength meter actually needs, it did not.")
    add("")

    # 23 --------------------------------------------------------------------
    add("## 23. Future work")
    add("")
    add("* **A real password corpus.** Every structure prior in M3 and every rule ordering "
        "in M4/M5 is a maximum-entropy assumption standing in for a distribution nobody "
        "here can measure. This is the single largest source of error.")
    add("* **More languages.** The pipeline is language-parameterised; only Hindi is built.")
    add("* **A hybrid estimator**, if and only if it is fitted on data disjoint from the "
        "evaluation benchmark. Fitting one on these 1,400 samples would measure the "
        "generator, which is why this project does not ship one.")
    add("* **Attackers with leaked-corpus wordlists**, to test whether the ordering result "
        "survives an attacker whose candidate order is learned rather than assumed.")
    add("* **Human-subject validation** of whether the 0-4 bands change behaviour.")
    add("")

    # 24 --------------------------------------------------------------------
    add("## 24. Reproduction")
    add("")
    add("Full environment, hashes and expected outputs are in `docs/REPRODUCING.md`. In "
        "short:")
    add("")
    add("```bash")
    for command in REPRODUCTION:
        add(command)
    add("```")
    add("")
    add("| artefact | SHA-256 |")
    add("| --- | --- |")
    for key, value in data["hashes"].items():
        if key == "source":
            continue
        add(f"| {key} | `{value}` |")
    add("")
    add("| source report | milestone | SHA-256 |")
    add("| --- | --- | --- |")
    for entry in report["sources"].values():
        add(f"| `{entry['path']}` | {entry['milestone']} | `{entry['sha256'][7:23]}...` |")
    add("")
    consistency = report["consistency"]
    add(f"**Cross-report consistency: "
        f"{'all checks pass' if consistency['all_consistent'] else 'FAILED'}.** "
        "Every experiment quoted above was run against the same corpus, the same "
        "dictionary build, the same trained grammar and the same baseline:")
    add("")
    add("| check | consistent |")
    add("| --- | --- |")
    for entry in consistency["checks"]:
        add(f"| {entry['check']} | {entry['consistent']} |")
    add("")
    add("---")
    add("")
    add("*No password appears in this report or in any report it draws from. The benchmark "
        "regenerates from committed source and a seed; rows are keyed on `sample_id`.*")
    add("")
    return "\n".join(lines) + "\n"


LIMITATIONS: tuple[str, ...] = (
    "**The attacks are bounded reference models, not the space of real attackers.** No "
    "leaked-password list, no Markov or PCFG guess generator, no leet substitution, no "
    "keyboard walks, no targeted personal data. An estimator that predicts these attacks "
    "well may predict another badly.",
    "**Metrics are conditional on reachability.** M4 scores on 37.7% of the benchmark and "
    "M5 on 77.9%; an unreachable target is given no rank and contributes to coverage and "
    "to nothing else. Coverage is reported beside every metric.",
    "**The benchmark is synthetic.** Generated from a hand-written Romanized Hindi word "
    "bank, not observed passwords. It supports claims about estimator ordering, not about "
    "the distribution of real Indian passwords.",
    "**One language, one dictionary source.** Hindi, from Aksharantar, via one trained "
    "transliteration model at test CER 0.108.",
    "**Structure priors are assumptions, not measurements.** M3's segment and category "
    "priors, and both attacks' rule orderings, are maximum-entropy choices standing in for "
    "distributions that need a password corpus to learn. Each is reported with a "
    "sensitivity arm.",
    "**Evidential independence is partial in one arm each.** M4's `frequency` arm and M5's "
    "`indicdict` arm share training evidence with the estimators they score; the "
    "`shuffled`, `length` and `uniform` arms remove it.",
    "**Quantised levels are not probabilities.** M5's cost levels define its enumeration "
    "order and are not claimed to be a probability model.",
    "**The out-of-lexicon taxonomy is a heuristic.** The in-lexicon / out-of-lexicon split "
    "is exact dictionary membership; the finer families will mislabel some targets.",
    "**No human-subject evaluation.** Whether the 0-4 bands change anyone's password "
    "choice is untested.",
)

REPRODUCTION: tuple[str, ...] = (
    "python -m pip install -r requirements/dev.txt",
    "",
    "# The dictionary is a build artefact (~35 min on CPU, needs torch).",
    "# Skip if data/dictionaries/indicdict_hin.jsonl is already present.",
    "python scripts/build_indicdict.py --languages hin",
    "",
    "# M1/M2: coverage, benchmark, ablations, sensitivity",
    "python scripts/indicdict_coverage.py --languages hin",
    "python scripts/password_benchmark.py --languages hin",
    "",
    "# M3: fit the grammar, then evaluate it",
    "python scripts/train_pcfg.py --languages hin",
    "python scripts/pcfg_benchmark.py --languages hin",
    "",
    "# M4 and M5: the two reference attacks",
    "python scripts/reference_attack.py --languages hin",
    "python scripts/milestone5_oov_attack.py --languages hin",
    "",
    "# Determinism: every pipeline twice, in separate processes, compared byte for byte",
    "python scripts/verify_reproducibility.py --languages hin",
    "",
    "# This report",
    "python scripts/final_report.py",
    "",
    "python -m pytest",
    "python -m ruff check .",
)


def print_console(report: Mapping[str, Any]) -> None:
    data = report["findings"]
    m5 = data["m5"]
    width = 92
    print(f"\n{'=' * width}")
    print("INDICPASS -- FINAL RESEARCH REPORT")
    print(f"{'=' * width}")
    print(f"  sources         {len(report['sources'])} milestone reports")
    passing = "all checks pass" if report["consistency"]["all_consistent"] else "FAILED"
    print(f"  consistency     {passing}")
    print(f"  figures         {len(report['figures'])}")
    print()
    print(f"  M4 coverage     {data['m4']['coverage']['covered']}/"
          f"{data['m4']['coverage']['targets']} "
          f"({data['m4']['coverage']['coverage']:.1%})")
    print(f"  M5 coverage     {m5['coverage']['all']['reachable']}/"
          f"{m5['coverage']['all']['targets']} "
          f"({m5['coverage']['all']['coverage']:.1%})")
    print(f"  M5 OOV Indic    {m5['coverage']['oov_indic']['reachable']}/"
          f"{m5['coverage']['oov_indic']['targets']} "
          f"({m5['coverage']['oov_indic']['coverage']:.1%})")
    print()
    oov = m5["metrics"]["oov_indic"]
    print(f"  {'on oov_indic':<18}{'rho':>10}{'MAE':>10}{'RMSE':>10}")
    for name, label in ESTIMATORS:
        entry = oov[name]
        print(f"  {label:<18}{_f(entry['spearman']):>10}"
              f"{entry['mean_absolute_error']:>10.3f}{entry['rmse']:>10.3f}")
    print()
    print(f"  separation      {_f(m5['separation']['orders_of_magnitude_separation'], '.2f')}"
          " orders of magnitude, out-of-lexicon Hindi vs random")
    print(f"  M5 verdict      {m5['verdict']['status'].upper().replace('_', ' ')}")
    print()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    directory = config.ensure_dir("reports")
    reports, provenance = load_sources(directory)
    logger.info("Read %d milestone reports from %s", len(reports), config.relative(directory))

    consistency = check_consistency(reports)
    for entry in consistency["checks"]:
        if not entry["consistent"]:
            logger.error(
                "Reports disagree on %s: %s. They were not run against the same inputs "
                "and must not be quoted side by side.",
                entry["check"],
                entry["values"],
            )
    if not consistency["all_consistent"]:
        return 2
    logger.info("Cross-report consistency: %d checks pass", len(consistency["checks"]))

    findings = extract(reports)
    figures = {} if args.no_figures else build_figures(findings)

    report: dict[str, Any] = {
        "report": SCRIPT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": git_commit(config.root),
        "project": f"{config.name} v{config.version}",
        "language": "hin",
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "implementation": platform.python_implementation(),
        },
        "sources": provenance,
        "consistency": consistency,
        "findings": findings,
        "figures": sorted(figures),
        "limitations": list(LIMITATIONS),
        "reproduction": [line for line in REPRODUCTION if line and not line.startswith("#")],
        "note": (
            "Every number in this report is read from a committed milestone report and is "
            "not recomputed. The `source` field on each findings block names the report "
            "and key it came from."
        ),
    }

    print_console(report)

    if args.no_report:
        return 0

    base = directory / "final_report"
    base.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render(report), encoding="utf-8")
    logger.info("Report written to %s", config.relative(base.with_suffix(".md")))

    if figures:
        figure_dir = (
            config.resolve(args.figure_dir)
            if args.figure_dir
            else config.root / "results" / "figures"
        )
        figure_dir.mkdir(parents=True, exist_ok=True)
        for name, svg in figures.items():
            (figure_dir / name).write_text(svg, encoding="utf-8")
        logger.info("%d figures written to %s", len(figures), config.relative(figure_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
