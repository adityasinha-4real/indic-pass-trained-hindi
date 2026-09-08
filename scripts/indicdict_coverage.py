#!/usr/bin/env python
"""Measure how much everyday Romanized Hindi IndicDict actually contains.

    python scripts/indicdict_coverage.py
    python scripts/indicdict_coverage.py --languages hin --no-report

The guess model can only recognise words the dictionary holds, so its coverage
is the ceiling on everything else. This script measures that ceiling against a
curated probe set -- the same word bank the benchmark builds its Indic
categories from -- and writes the result whether it is flattering or not.

The probe set is an INSTRUMENT, not a target
--------------------------------------------
The words come from ``indicpass.password.benchmark.INDIC_WORDS``: everyday
greetings, kinship terms, common nouns, and the given names and surnames that
dominate Indian password dumps. They were written from usage and deliberately
not sampled from IndicDict, because a probe drawn from the dictionary would
report 100% and mean nothing.

Words are never added to the dictionary to improve this number. A dictionary
tuned until it recognised the demo would tell us nothing about whether Indic
awareness helps in general, which is the only question worth asking.

What it reports, per word
-------------------------
present / absent, the native form the transliterator produced, the observed
frequency and rank if any, the pricing policy that would apply, and the
Aksharantar subsource the pair came from. Plus, in aggregate: coverage overall
and by tier, how much of the dictionary is priced by evidence rather than by
fallback, and the accidental-hit probability by token length -- the measurement
the matcher's substring threshold is calibrated from.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config
from indicpass.password.benchmark import GENERATOR_VERSION, INDIC_WORDS
from indicpass.password.dictionary import OBSERVED_RANK, IndicDict
from indicpass.password.mangling import normalize_for_lookup

SCRIPT = "indicdict_coverage"

#: The fifteen words named in the milestone brief. Reported separately from the
#: full bank so the headline number cannot drift as the bank grows.
CORE_PROBE: tuple[str, ...] = (
    "namaste", "namaskar", "dhanyavaad", "dhanyavad", "bharat", "krishna",
    "sharma", "aditya", "mera", "pyaar", "prem", "maa", "papa", "dost", "ghar",
)

#: Generic English password vocabulary, probed for the opposite reason: a
#: Romanized-*Hindi* dictionary has no business containing these, and where it
#: does, the overlap is a confound the benchmark's English control has to be
#: read against. It is not hypothetical -- Aksharantar's `Existing` subsource is
#: a transliteration corpus, and `password` and `qwerty` have legitimate
#: Devanagari transliterations in it.
CONTROL_PROBE: tuple[str, ...] = (
    "password", "welcome", "football", "qwerty", "letmein",
    "monkey", "dragon", "master", "shadow", "superman",
)

#: Token lengths the accidental-hit table covers.
_PROBE_LENGTHS = range(3, 11)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="indicdict_coverage.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--dictionary", type=Path, metavar="FILE", help="Dictionary to probe. Default from config."
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        metavar="FILE",
        help="Report path without suffix. Default results/reports/indicdict_coverage_<lang>.",
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


def probe(dictionary: IndicDict, words: Sequence[str]) -> list[dict[str, Any]]:
    """One row per probe word: what the dictionary knows about it, if anything."""
    rows: list[dict[str, Any]] = []
    for word in words:
        entry = dictionary.get(normalize_for_lookup(word))
        if entry is None:
            rows.append({"word": word, "present": False})
            continue
        position = dictionary.guess_position(entry)
        rows.append(
            {
                "word": word,
                "present": True,
                "native_form": entry.native_form,
                "tier": entry.tier,
                "source": entry.source,
                "model_verified": entry.model_verified,
                "frequency": entry.frequency,
                "rank": entry.rank,
                "frequency_source": entry.frequency_source,
                "frequency_matched_via": entry.frequency_matched_via,
                "rank_policy": position.policy,
                "wordlist_position": round(position.position, 2),
            }
        )
    return rows


def accidental_hit_rates(dictionary: IndicDict) -> list[dict[str, Any]]:
    """P(a random lower-case string of length L is a dictionary key), exactly.

    Computed, not sampled: the number of keys of that length over 26**L. This
    is the measurement ``matching.min_substring_length`` is calibrated from --
    the length at which a hit stops being more likely than not to be an
    accident.
    """
    lengths = Counter(len(word) for word in dictionary.entries)
    return [
        {
            "length": length,
            "entries": lengths[length],
            "space": 26**length,
            "probability": lengths[length] / 26**length,
        }
        for length in _PROBE_LENGTHS
    ]


def summarise(rows: Sequence[dict[str, Any]]) -> dict[str, Any]:
    present = [row for row in rows if row["present"]]
    ranked = [row for row in present if row["rank_policy"] == OBSERVED_RANK]
    return {
        "probed": len(rows),
        "present": len(present),
        "absent": len(rows) - len(present),
        "coverage": round(len(present) / len(rows), 4) if rows else 0.0,
        "priced_by_observed_rank": len(ranked),
        "priced_by_tier_fallback": len(present) - len(ranked),
        "rank_coverage_of_present": (
            round(len(ranked) / len(present), 4) if present else 0.0
        ),
    }


def build_report(
    *, config: Config, dictionary: IndicDict, path: Path, language: str
) -> dict[str, Any]:
    full_rows = probe(dictionary, INDIC_WORDS)
    core_rows = probe(dictionary, CORE_PROBE)
    control_rows = probe(dictionary, CONTROL_PROBE)

    by_tier = Counter(row["tier"] for row in full_rows if row["present"])

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": f"{config.name} v{config.version}",
        "git_commit": git_commit(config.root),
        "dictionary": {
            "language": language,
            "file": config.relative(path),
            "entries": len(dictionary),
            "ranked_entries": dictionary.ranked_total,
            "frequency_coverage": round(dictionary.frequency_coverage, 6),
            "frequency_source": dictionary.frequency_source,
            "built_at": dictionary.metadata.get("built_at"),
            "built_from_commit": dictionary.metadata.get("git_commit"),
            "tiers": [
                tier.to_dict()
                for tier in sorted(dictionary.tiers.values(), key=lambda t: t.index)
            ],
        },
        "probe_set": {
            "source": "indicpass.password.benchmark.INDIC_WORDS",
            "generator_version": GENERATOR_VERSION,
            "words": len(INDIC_WORDS),
            "note": (
                "Written from usage, not sampled from IndicDict. No word is ever added "
                "to the dictionary because it appears here."
            ),
        },
        "core_probe": {"words": list(CORE_PROBE), **summarise(core_rows), "rows": core_rows},
        "control_probe": {
            "words": list(CONTROL_PROBE),
            **summarise(control_rows),
            "rows": control_rows,
            "note": (
                "Generic English password vocabulary. Any coverage here is accidental "
                "overlap from Aksharantar's transliteration subsources, and it is a "
                "confound the benchmark's English control must be read against -- not "
                "evidence of Indic awareness."
            ),
        },
        "full_probe": {**summarise(full_rows), "by_tier": dict(by_tier), "rows": full_rows},
        "accidental_hit_rates": accidental_hit_rates(dictionary),
    }


def render_markdown(report: dict[str, Any]) -> str:
    dictionary = report["dictionary"]
    core = report["core_probe"]
    control = report["control_probe"]
    full = report["full_probe"]
    source = dictionary["frequency_source"] or {}

    lines = [
        f"# IndicDict coverage -- {dictionary['language']}",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Git commit:** `{report['git_commit']}`",
        f"- **Dictionary:** `{dictionary['file']}` "
        f"({dictionary['entries']:,} entries, built {dictionary['built_at']})",
        f"- **Frequency source:** `{source.get('identifier', 'none')}`"
        + (f" -- {source['semantics']}" if source.get("semantics") else ""),
        f"- **Probe set:** {report['probe_set']['words']} words from "
        f"`{report['probe_set']['source']}` (generator {report['probe_set']['generator_version']})",
        "",
        report["probe_set"]["note"],
        "",
        "## Headline",
        "",
        "| Probe | Words | Present | Absent | Coverage | Priced by rank | By tier fallback |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| Core (brief) | {core['probed']} | {core['present']} | {core['absent']} "
        f"| {core['coverage'] * 100:.1f}% | {core['priced_by_observed_rank']} "
        f"| {core['priced_by_tier_fallback']} |",
        f"| Full bank | {full['probed']} | {full['present']} | {full['absent']} "
        f"| {full['coverage'] * 100:.1f}% | {full['priced_by_observed_rank']} "
        f"| {full['priced_by_tier_fallback']} |",
        f"| English controls | {control['probed']} | {control['present']} "
        f"| {control['absent']} | {control['coverage'] * 100:.1f}% "
        f"| {control['priced_by_observed_rank']} | {control['priced_by_tier_fallback']} |",
        "",
        "## Dictionary-wide pricing",
        "",
        f"{dictionary['ranked_entries']:,} of {dictionary['entries']:,} entries "
        f"({dictionary['frequency_coverage'] * 100:.1f}%) have an observed corpus frequency "
        "and are priced by measured rank. The rest fall back to their provenance tier.",
        "",
        "| Tier | Entries | Ranked | Unranked | Fallback offset |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {tier['name']} | {tier['size']:,} | {tier['ranked_size']:,} "
        f"| {tier['unranked_size']:,} | {tier['offset']:,} |"
        for tier in dictionary["tiers"]
    ]

    lines += [
        "",
        "## Core probe, word by word",
        "",
        "| Word | Present | Native form | Tier | Source | Frequency | Rank | Priced by |",
        "| --- | :---: | --- | --- | --- | ---: | ---: | --- |",
    ]
    for row in core["rows"]:
        if not row["present"]:
            lines.append(f"| `{row['word']}` | no | -- | -- | -- | -- | -- | -- |")
            continue
        frequency = "--" if row["frequency"] is None else f"{row['frequency']:.2f}"
        rank = "--" if row["rank"] is None else f"{row['rank']:,}"
        lines.append(
            f"| `{row['word']}` | yes | {row['native_form']} | {row['tier']} "
            f"| {row['source']} | {frequency} | {rank} | {row['rank_policy']} |"
        )

    lines += [
        "",
        "## English controls -- the accidental-overlap confound",
        "",
        control["note"],
        "",
        "| Word | Present | Native form | Tier | Source | Priced by |",
        "| --- | :---: | --- | --- | --- | --- |",
    ]
    for row in control["rows"]:
        if not row["present"]:
            lines.append(f"| `{row['word']}` | no | -- | -- | -- | -- |")
            continue
        lines.append(
            f"| `{row['word']}` | **yes** | {row['native_form']} | {row['tier']} "
            f"| {row['source']} | {row['rank_policy']} |"
        )

    lines += [
        "",
        "## Words absent from the dictionary",
        "",
        "These are not filtering artefacts -- they are absent from Aksharantar's Hindi",
        "split entirely, at source. Aksharantar is a transliteration benchmark built from",
        "named entities and mined pairs, not a lexicon of what people type.",
        "",
    ]
    absent = [row["word"] for row in full["rows"] if not row["present"]]
    lines += ["  " + ", ".join(f"`{word}`" for word in absent) if absent else "  (none)"]

    lines += [
        "",
        "## Accidental hits by token length",
        "",
        "The probability that a random lower-case string of length L is a dictionary key.",
        "This is what `matching.min_substring_length` is calibrated from: below the length",
        "where a hit becomes surprising, a match is close to no evidence at all.",
        "",
        "| Length | Entries | Search space | P(random string is a key) |",
        "| ---: | ---: | ---: | ---: |",
    ]
    lines += [
        f"| {row['length']} | {row['entries']:,} | {row['space']:,} | {row['probability']:.3e} |"
        for row in report["accidental_hit_rates"]
    ]

    lines += [
        "",
        "## How to read this",
        "",
        "Coverage is the ceiling on everything the guess model can do. A word the",
        "dictionary does not hold cannot be recognised however good the scoring is, and",
        "the missing words here are among the commonest in the language. Any benchmark",
        "result for the Indic categories should be read against this table first.",
        "",
    ]
    return "\n".join(lines) + "\n"


def print_console(report: dict[str, Any]) -> None:
    dictionary = report["dictionary"]
    core = report["core_probe"]
    full = report["full_probe"]

    print(f"\n{'=' * 74}")
    print(f"INDICDICT COVERAGE -- {dictionary['language']}")
    print(f"{'=' * 74}")
    print(f"  entries              {dictionary['entries']:,}")
    print(f"  priced by rank       {dictionary['ranked_entries']:,} "
          f"({dictionary['frequency_coverage'] * 100:.1f}%)")
    print(f"  core probe           {core['present']}/{core['probed']} present "
          f"({core['coverage'] * 100:.1f}%)")
    print(f"  full probe           {full['present']}/{full['probed']} present "
          f"({full['coverage'] * 100:.1f}%)")
    absent = [row["word"] for row in core["rows"] if not row["present"]]
    if absent:
        print(f"  absent from core     {', '.join(absent)}")
    control = report["control_probe"]
    overlap = [row["word"] for row in control["rows"] if row["present"]]
    print(f"  english controls     {control['present']}/{control['probed']} present"
          + (f" -- {', '.join(overlap)}" if overlap else ""))
    print()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("Probe one language at a time. Pass --languages hin.")
        return 2
    language = languages[0]

    dictionary_config = config.password_section("dictionary")
    tier_order = [str(tier["name"]) for tier in dictionary_config.get("tiers") or []]
    path = config.resolve(
        args.dictionary or (dictionary_config.get("files") or {})[language.code]
    )

    logger.info("Loading %s", config.relative(path))
    dictionary = IndicDict.load(path, language=language.code, tier_order=tier_order)

    report = build_report(
        config=config, dictionary=dictionary, path=path, language=language.code
    )
    print_console(report)

    if not args.no_report:
        prefix = config.password_section("evaluation").get("coverage", {}).get(
            "report_prefix", "indicdict_coverage"
        )
        base = (
            config.resolve(args.output)
            if args.output
            else config.ensure_dir("reports") / f"{prefix}_{language.code}"
        )
        base.parent.mkdir(parents=True, exist_ok=True)
        base.with_suffix(".json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        base.with_suffix(".md").write_text(render_markdown(report), encoding="utf-8")
        logger.info("Report written to %s", config.relative(base.with_suffix(".md")))

    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
