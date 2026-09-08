#!/usr/bin/env python
"""Analyse one password with the IndicPass meter.

    python scripts/check_password.py --password "namaste123"
    python scripts/check_password.py --password "namaste123" --json
    python scripts/check_password.py            # prompts, without echoing

The password is read, scored and discarded. It is never printed back, never
logged and never written to a file -- the report says what was *found* in it
(a 7-character Hindi word, a 3-digit suffix) and how many guesses that costs,
which is the useful part anyway.

Prefer the interactive prompt to ``--password``: a password on the command line
ends up in the shell history and in the process list.
"""

from __future__ import annotations

import argparse
import getpass
import json
import sys
from collections.abc import Sequence
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.password.meter import IndicPassMeter, describe_dictionaries, describe_pcfg
from indicpass.password.result import PasswordStrengthResult

SCRIPT = "check_password"

#: Human labels for the pattern names the matcher emits.
PATTERN_LABELS = {
    "indic_word": "Indic dictionary match",
    "digits": "numeric run",
    "year": "year",
    "symbols": "symbol run",
    "repeat": "repeated characters",
    "bruteforce": "unrecognised",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="check_password.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--password",
        "-p",
        metavar="TEXT",
        help="Password to analyse. Prompts without echo when omitted (preferred).",
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit JSON. Matched substrings are redacted."
    )
    parser.add_argument(
        "--show-tokens",
        action="store_true",
        help=(
            "Include the matched substrings in JSON output. They are pieces of "
            "the password -- never redirect this into a file."
        ),
    )
    return parser


def read_password(args: argparse.Namespace) -> str:
    if args.password is not None:
        return args.password
    if not sys.stdin.isatty():
        raise SystemExit("No password given. Pass --password, or run interactively to be prompted.")
    return getpass.getpass("Password (not echoed): ")


#: Human labels for the PCFG's terminal categories.
PCFG_CATEGORY_LABELS = {
    "word": "Indic dictionary word",
    "unknown": "unseen spelling, priced by the character model",
    "digits": "numeric run",
    "year": "year",
    "symbols": "symbol run",
}


def render_pcfg(estimate: Any) -> list[str]:
    """The grammar's derivation, segment by segment.

    Printed in full because a guess estimate nobody can argue with is not a
    research result. The three numbers at the end are the ones that matter:
    what the grammar said, what enumerating the string would cost, and which of
    the two produced the answer.
    """
    lines = ["PCFG (Milestone 3, reported alongside -- it does not replace the above):"]
    if not estimate.supported:
        lines.append("  no derivation covers this password; the grammar says nothing")
    for segment in estimate.segments:
        label = PCFG_CATEGORY_LABELS.get(segment["category"], segment["category"])
        detail = ""
        if segment["category"] == "word":
            detail = (
                f", rank {segment['rank']:,}"
                if segment.get("rank")
                else f", no observed frequency ({segment.get('tier')} tier)"
            )
        lines.append(
            f"  chars {segment['start']}-{segment['end']}  ->  {label}"
            f"  [log10 P {segment['log10_probability']:.2f}{detail}]"
        )
    lines += [
        f"  log10 P(password):  {estimate.log10_probability:.2f}",
        f"  grammar:            {estimate.grammar_log10_guesses:.2f} log10 guesses",
        f"  brute force:        {estimate.bruteforce_log10_guesses:.2f} log10 guesses"
        f"   (not a production of the grammar)",
        f"  reported:           {estimate.log10_guesses:.2f} log10 guesses, "
        f"score {estimate.score}/4"
        f"{'  -- the floor won' if estimate.floor_applied else ''}",
        "",
    ]
    return lines


def render(result: PasswordStrengthResult, meter: IndicPassMeter) -> str:
    lines = [
        "",
        "IndicPass Password Analysis",
        "=" * 46,
        "",
        f"Length: {result.password_length}",
        "",
    ]

    indic = [m for m in result.matched_patterns if m.pattern == "indic_word"]
    if indic:
        lines.append("Indic patterns:")
        for match in indic:
            kind = "name" if match.detail.get("is_named_entity") else "word"
            verified = "model-verified" if match.detail.get("model_verified") else "unverified"
            lines.append(
                f"  chars {match.start}-{match.end}  ->  Hindi dictionary {kind} "
                f"[{match.detail.get('match_class')}, {match.detail.get('tier')}, {verified}]"
            )
            lines.append(
                f"      renders as {match.detail.get('native_form')}   "
                f"case: {match.detail.get('case_transformation')}"
            )
            # Say which pricing policy produced the number, every time. A rank
            # is a measurement; a tier position is a policy for the unknown,
            # and the two must not look alike on the way out.
            if match.detail.get("rank_policy") == "observed_rank":
                lines.append(
                    f"      wordlist rank {match.detail['rank']:,} "
                    f"(corpus frequency {match.detail['frequency']}, "
                    f"{match.detail.get('frequency_source')})"
                )
            else:
                lines.append(
                    f"      no observed frequency -- priced by the {match.detail.get('tier')} "
                    f"tier fallback at position "
                    f"{match.detail.get('wordlist_position'):,.0f}"
                )
    else:
        lines.append("Indic patterns:  none found")
    lines.append("")

    other = [m for m in result.matched_patterns if m.pattern != "indic_word"]
    if other:
        lines.append("Other components:")
        for match in other:
            label = PATTERN_LABELS.get(match.pattern, match.pattern)
            lines.append(
                f"  chars {match.start}-{match.end}  ->  {label} "
                f"({match.length} chars, {match.guesses:,.0f} guesses)"
            )
        lines.append("")

    lines += [
        f"Estimated guesses: {result.guess_number:,.0f}",
        f"log10 guesses:     {result.log10_guesses:.2f}",
        "",
        f"IndicPass score: {result.strength_score}/4",
        f"Strength: {result.strength_label}",
        "",
    ]

    if result.warnings:
        lines.append("Findings:")
        lines += [f"  - {note}" for note in result.warnings]
        lines.append("")

    # State the baseline's absence rather than leaving a blank where a number
    # belongs; an empty slot reads as "the same" to a hurried reader.
    if result.baseline is not None and meter.baseline is not None:
        estimate = result.baseline
        lines += [
            f"{meter.baseline.name} baseline ({meter.baseline.version}):",
            f"  guesses:  {estimate.guesses:,.0f}   log10 {estimate.log10_guesses:.2f}   "
            f"score {estimate.score}/4",
            f"  read as:  {', '.join(estimate.patterns) or 'nothing recognised'}",
            "",
        ]
    else:
        lines += ["Baseline: not available in this run; no comparison is possible.", ""]

    if result.pcfg is not None:
        lines += render_pcfg(result.pcfg)

    if result.baseline is not None or result.pcfg is not None:
        # An attacker holds every model they can get, and guessing cost is a
        # minimum -- so this, not any single column, is the number that
        # describes the password.
        lines += [
            f"Against an attacker holding every model above: "
            f"{result.combined_log10_guesses:.2f} log10 guesses",
            "",
        ]

    lines.append("Dictionaries used:")
    for info in describe_dictionaries(meter):
        source = (info.get("frequency_source") or {}).get("identifier", "none")
        lines.append(
            f"  {info['language']}: {info['entries']:,} entries, "
            f"{info['ranked_entries']:,} priced by measured rank "
            f"({info['frequency_coverage'] * 100:.1f}%, source {source})"
        )
    lines.append("")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, _logger = startup(args, SCRIPT)

    meter = IndicPassMeter.from_config(config, languages=args.languages or None)
    password = read_password(args)
    if not password:
        print("Empty password.", file=sys.stderr)
        return 1

    result = meter.score(password)

    if args.json:
        payload = result.to_dict(include_tokens=args.show_tokens)
        payload["dictionaries"] = describe_dictionaries(meter)
        payload["estimators"] = {
            "indicpass": True,
            "baseline": meter.baseline.name if meter.baseline else None,
            "pcfg": describe_pcfg(meter) is not None,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render(result, meter))

    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
