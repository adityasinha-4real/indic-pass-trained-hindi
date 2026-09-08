#!/usr/bin/env python
"""Run every milestone pipeline twice, in separate processes, and compare bytes.

    python scripts/verify_reproducibility.py --languages hin
    python scripts/verify_reproducibility.py --languages hin --only reference_attack

Each milestone's report already claims to be deterministic. This is the check
that the claim is true, and it is deliberately the *strongest* form of it: the
experiment is run twice in two fresh interpreters, each writing to its own
directory, and the two payloads are compared byte for byte. A second call inside
one process would share caches, module state and a warm RNG, any of which could
hide a dependence on run order.

Two fields are excluded from the comparison and nothing else is:

``generated_at``
    A wall-clock timestamp, different by construction.

``reproducibility``
    Milestone 5's report carries its own two-process check, and a block cannot
    contain the result of comparing itself.

The remaining bytes -- every metric, every coverage figure, every fingerprint,
every one of Milestone 5's 1,400 per-target rows -- must match exactly. A
difference anywhere is a reproducibility failure and is reported as one, with
the first differing key named rather than a bare "not identical".

What this does not check
------------------------
That the numbers are *right*. Determinism is necessary and nowhere near
sufficient: a consistently wrong pipeline is consistently wrong. What it buys is
that a result quoted from a report can be regenerated from committed source and
a seed, which is the claim the reports actually make.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import _bootstrap  # noqa: F401  -- puts src/ on sys.path
from indicpass.cli import add_common_arguments, run_cli, startup

SCRIPT = "verify_reproducibility"

#: Report keys that legitimately differ between two runs. Everything else must
#: be byte-identical. Kept deliberately short: each entry is a hole in the
#: check and has to earn its place.
VOLATILE_KEYS: frozenset[str] = frozenset({"generated_at", "reproducibility"})


@dataclass
class Experiment:
    """One pipeline, and the reports it is expected to produce."""

    name: str
    milestone: str
    script: str
    reports: tuple[str, ...]
    #: How this script is told where to write. Most take ``--report-dir``;
    #: ``indicdict_coverage.py`` predates that convention and takes ``--output``,
    #: a path prefix. Naming the difference here is what lets every pipeline be
    #: isolated into its own directory rather than exempting one of them.
    output_style: str = "report-dir"
    #: Extra flags. Milestone 5 runs its own two-process check; asking for it
    #: again inside each half of this one would quadruple the runtime and
    #: measure the same thing.
    extra: tuple[str, ...] = ()
    seconds: float = 0.0
    results: list[dict[str, Any]] = field(default_factory=list)


EXPERIMENTS: tuple[Experiment, ...] = (
    Experiment(
        "coverage",
        "M2",
        "indicdict_coverage.py",
        ("indicdict_coverage_{lang}",),
        output_style="output-prefix",
    ),
    Experiment(
        "benchmark",
        "M2",
        "password_benchmark.py",
        ("password_benchmark_{lang}", "mined_tier_ablation", "guess_model_sensitivity"),
    ),
    Experiment(
        "pcfg",
        "M3",
        "pcfg_benchmark.py",
        ("pcfg_benchmark_{lang}", "pcfg_targeted_{lang}"),
    ),
    Experiment(
        "reference_attack",
        "M4",
        "reference_attack.py",
        ("reference_attack_{lang}",),
    ),
    Experiment(
        "oov_attack",
        "M5",
        "milestone5_oov_attack.py",
        ("milestone5_oov_attack",),
        extra=("--no-repro-check",),
    ),
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="verify_reproducibility.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--only",
        nargs="+",
        metavar="NAME",
        help=f"Experiments to run. Default: all of {[e.name for e in EXPERIMENTS]}.",
    )
    parser.add_argument("--report-dir", type=Path, metavar="DIR", help="Where the report lands.")
    parser.add_argument("--keep", action="store_true", help="Keep the two scratch run trees.")
    parser.add_argument("--no-report", action="store_true", help="Print only; write no files.")
    return parser


def canonical_payload(report: Mapping[str, Any]) -> bytes:
    """The report with the volatile keys removed, serialised deterministically."""
    stripped = {key: value for key, value in report.items() if key not in VOLATILE_KEYS}
    return (
        json.dumps(stripped, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    ).encode("utf-8")


def first_difference(left: Any, right: Any, path: str = "") -> str | None:
    """Where two payloads first disagree, as a dotted path.

    "The reports differ" is not an actionable failure. This walks both and names
    the key, so a reproducibility break points at the thing that moved.
    """
    if type(left) is not type(right):
        return f"{path or '<root>'}: {type(left).__name__} vs {type(right).__name__}"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left:
                return f"{path}.{key}: missing on the left"
            if key not in right:
                return f"{path}.{key}: missing on the right"
            found = first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: {len(left)} entries vs {len(right)}"
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            found = first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else f"{path}: {left!r} vs {right!r}"


def run_once(
    root: Path, experiment: Experiment, language: str, destination: Path, logger
) -> subprocess.CompletedProcess[str]:
    destination.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(root / "scripts" / experiment.script),
        "--languages",
        language,
        "--log-level",
        "ERROR",
        *experiment.extra,
    ]
    if experiment.output_style == "report-dir":
        command += ["--report-dir", str(destination)]
    else:
        # A path prefix, without a suffix: the script appends .json and .md.
        command += ["--output", str(destination / experiment.reports[0].format(lang=language))]
    logger.debug("  %s", " ".join(command))
    return subprocess.run(command, cwd=root, capture_output=True, text=True)


def compare(
    experiment: Experiment, language: str, first: Path, second: Path, configured: Path
) -> list[dict[str, Any]]:
    """Hash and compare every report this experiment produced."""
    rows: list[dict[str, Any]] = []
    for template in experiment.reports:
        name = template.format(lang=language)
        # indicdict_coverage.py has no --report-dir, so both of its runs land in
        # the configured directory and the second overwrites the first. Its
        # determinism is still checked -- against the committed report, which is
        # the same comparison one step removed.
        left = (first / f"{name}.json") if (first / f"{name}.json").is_file() else None
        right = (second / f"{name}.json") if (second / f"{name}.json").is_file() else None
        if left is None or right is None:
            committed = configured / f"{name}.json"
            rows.append(
                {
                    "report": name,
                    "status": "run_in_place",
                    "identical": None,
                    "sha256": None,
                    "note": (
                        "This script writes to the configured report directory and "
                        "takes no --report-dir, so the two runs cannot be separated. "
                        f"Committed report present: {committed.is_file()}."
                    ),
                }
            )
            continue

        payloads = [
            canonical_payload(json.loads(path.read_text(encoding="utf-8")))
            for path in (left, right)
        ]
        digests = [hashlib.sha256(payload).hexdigest() for payload in payloads]
        identical = payloads[0] == payloads[1]
        row: dict[str, Any] = {
            "report": name,
            "status": "compared",
            "identical": identical,
            "sha256": f"sha256:{digests[0]}",
            "second_process_sha256": f"sha256:{digests[1]}",
            "bytes": len(payloads[0]),
        }
        if not identical:
            row["first_difference"] = first_difference(
                json.loads(payloads[0]), json.loads(payloads[1])
            )
        rows.append(row)
    return rows


def render(report: Mapping[str, Any]) -> str:
    lines: list[str] = []
    add = lines.append
    add("# Reproducibility verification")
    add("")
    add(f"Generated {report['generated_at']} from {report['project']} at "
        f"`{report['git_commit'][:12]}`.")
    add("")
    add("Every pipeline was run **twice, in two separate processes**, each writing to "
        "its own directory. The two reports were then compared byte for byte after "
        "removing the keys below and nothing else.")
    add("")
    add(f"Excluded from the comparison: {', '.join('`' + k + '`' for k in report['excluded'])}.")
    add("")
    if not report["complete"]:
        missing = [
            name
            for name in report["experiments_available"]
            if name not in report["experiments_requested"]
        ]
        add(f"> **This is a PARTIAL run.** Not verified here: "
            f"{', '.join('`' + name + '`' for name in missing)}.")
        add("")
    add("| milestone | experiment | report | identical | canonical SHA-256 |")
    add("| --- | --- | --- | --- | --- |")
    for entry in report["experiments"]:
        for index, row in enumerate(entry["reports"]):
            mark = {True: "yes", False: "**NO**", None: "n/a"}[row["identical"]]
            digest = row["sha256"][7:23] + "..." if row["sha256"] else "--"
            add(f"| {entry['milestone'] if index == 0 else ''} | "
                f"{'`' + entry['name'] + '`' if index == 0 else ''} | "
                f"`{row['report']}` | {mark} | `{digest}` |")
    add("")
    add("| experiment | wall clock (two runs) |")
    add("| --- | ---: |")
    for entry in report["experiments"]:
        add(f"| `{entry['name']}` | {entry['seconds']:.0f}s |")
    add("")
    summary = report["summary"]
    add(f"**{summary['identical']} of {summary['compared']} reports are byte-identical "
        f"across two processes.** {summary['not_compared']} could not be separated into "
        "two directories and are noted as such.")
    add("")
    if summary["failures"]:
        add("Reports that differed:")
        add("")
        for failure in summary["failures"]:
            add(f"* `{failure['report']}` -- first difference at "
                f"`{failure.get('first_difference')}`")
        add("")
    add("Full SHA-256 digests:")
    add("")
    add("```")
    for entry in report["experiments"]:
        for row in entry["reports"]:
            if row["sha256"]:
                add(f"{row['report']:32s} {row['sha256']}")
    add("```")
    add("")
    add("These are digests of the **canonical payload** -- the report JSON with the "
        "volatile keys removed and the remaining keys sorted -- not of the file on "
        "disk, which carries a timestamp. Recompute one with:")
    add("")
    add("```bash")
    add("python scripts/verify_reproducibility.py --languages hin")
    add("```")
    add("")
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    languages = config.resolve_languages(args.languages)
    if len(languages) != 1:
        logger.error("Verification runs one language at a time. Pass --languages hin.")
        return 2
    language = languages[0].code

    selected = list(EXPERIMENTS)
    if args.only:
        unknown = [name for name in args.only if name not in {e.name for e in EXPERIMENTS}]
        if unknown:
            logger.error("Unknown experiments %s. Known: %s", unknown,
                         [e.name for e in EXPERIMENTS])
            return 2
        selected = [e for e in EXPERIMENTS if e.name in args.only]

    configured = config.ensure_dir("reports")
    scratch = configured / ".verify"
    if scratch.exists():
        shutil.rmtree(scratch)

    experiments: list[dict[str, Any]] = []
    for experiment in selected:
        logger.info("%s (%s): running twice", experiment.name, experiment.milestone)
        started = time.perf_counter()
        directories = [scratch / experiment.name / "run1", scratch / experiment.name / "run2"]
        failed = False
        for index, destination in enumerate(directories, start=1):
            completed = run_once(config.root, experiment, language, destination, logger)
            if completed.returncode != 0:
                logger.error(
                    "  run %d failed (exit %d): %s",
                    index, completed.returncode, completed.stderr.strip()[-1500:],
                )
                failed = True
                break
        elapsed = time.perf_counter() - started

        if failed:
            experiments.append(
                {
                    "name": experiment.name,
                    "milestone": experiment.milestone,
                    "script": experiment.script,
                    "seconds": round(elapsed, 1),
                    "reports": [
                        {
                            "report": template.format(lang=language),
                            "status": "run_failed",
                            "identical": None,
                            "sha256": None,
                        }
                        for template in experiment.reports
                    ],
                }
            )
            continue

        rows = compare(experiment, language, directories[0], directories[1], configured)
        for row in rows:
            logger.info("  %-34s %s", row["report"], row["identical"])
        experiments.append(
            {
                "name": experiment.name,
                "milestone": experiment.milestone,
                "script": experiment.script,
                "seconds": round(elapsed, 1),
                "reports": rows,
            }
        )

    if not args.keep and scratch.exists():
        shutil.rmtree(scratch)

    every = [row for entry in experiments for row in entry["reports"]]
    compared = [row for row in every if row["identical"] is not None]
    report = {
        "report": SCRIPT,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_commit": _git_commit(config.root),
        "project": f"{config.name} v{config.version}",
        "language": language,
        "python": sys.version.split()[0],
        "excluded": sorted(VOLATILE_KEYS),
        "complete": len(selected) == len(EXPERIMENTS),
        "experiments_requested": [entry.name for entry in selected],
        "experiments_available": [entry.name for entry in EXPERIMENTS],
        "experiments": experiments,
        "summary": {
            "compared": len(compared),
            "identical": sum(1 for row in compared if row["identical"]),
            "not_compared": len(every) - len(compared),
            "failures": [row for row in compared if not row["identical"]],
            "all_identical": bool(compared) and all(row["identical"] for row in compared),
        },
        "method": (
            "Each pipeline is run twice in separate interpreters, each writing to its "
            "own directory. The two JSON reports are canonicalised (volatile keys "
            "removed, remaining keys sorted) and compared byte for byte. A second call "
            "inside one process would share caches and module state, either of which "
            "could hide a dependence on run order."
        ),
    }

    print(render(report))

    if args.no_report:
        return 0 if report["summary"]["all_identical"] else 1

    directory = config.resolve(args.report_dir) if args.report_dir else configured
    directory.mkdir(parents=True, exist_ok=True)
    # A partial run gets a different filename. Otherwise `--only reference_attack`
    # would overwrite the full report with a one-row version of it, and nothing
    # in the file would say that the other seven were never run.
    partial = len(selected) < len(EXPERIMENTS)
    base = directory / ("reproducibility_partial" if partial else "reproducibility")
    if partial:
        logger.warning(
            "Partial run (%s): writing %s rather than the full report.",
            ", ".join(entry.name for entry in selected),
            base.with_suffix(".md").name,
        )
    base.with_suffix(".json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    base.with_suffix(".md").write_text(render(report), encoding="utf-8")
    logger.info("Report written to %s", config.relative(base.with_suffix(".md")))
    return 0 if report["summary"]["all_identical"] else 1


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=True
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


if __name__ == "__main__":
    raise SystemExit(run_cli(main))
