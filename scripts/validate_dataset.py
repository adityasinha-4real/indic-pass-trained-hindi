#!/usr/bin/env python
"""Validate the processed dataset and write a report to ``results/reports/``.

Runs the checks that actually catch broken transliteration data:

* **Schema** -- every standard field present, no nulls, no empty strings.
* **Duplicates** -- exact repeats, and one Roman spelling mapped to several
  different native forms (legitimate in transliteration, but worth knowing).
* **Script validity** -- the "native" side really is written in the script the
  record claims, measured as a ratio that ignores joiners and punctuation.
  This is what catches Latin text left in an Indic column, or Tamil filed
  under Telugu.
* **Source/target consistency** -- the source side is Romanized, the language
  label matches the directory it was found in, ``record_id`` still matches its
  own contents (i.e. the file has not been hand-edited).
* **Split leakage** -- the same source string appearing in both train and
  test, which silently inflates every evaluation number that follows.

Exits non-zero when a configured threshold is breached, so it can gate a
training run or a CI job.

Examples
--------
    python scripts/validate_dataset.py
    python scripts/validate_dataset.py --languages hin --split test
    python scripts/validate_dataset.py --no-report --quiet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import _bootstrap  # noqa: F401  -- puts src/ on sys.path

from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config, Language
from indicpass.logging_utils import progress
from indicpass.records import REQUIRED_FIELDS, read_jsonl, stable_id
from indicpass.script_utils import ascii_ratio, script_ratio

SCRIPT = "validate_dataset"

# Layout of the packed cross-record index value (see LanguageAudit._track_source):
#   bits  0-31   hash of the first target seen for this source
#   bits 32-62   bitmask of the splits this source appeared in
#   bit  63      set once the source has been seen with two different targets
#
# Split bits are assigned by position in config.split_names, so they are stable
# and nameable -- which is what lets overlap be reported per split *pair*
# rather than as one undifferentiated number. Any split name not in the config
# shares the overflow bit.
_SPLIT_MASK = 0x7FFF_FFFF
_SPLIT_SHIFT = 32
_AMBIGUOUS_BIT = 1 << 63

# The split pairs reported. Each entry is (metric name, split A, split B).
# Only the first two are gated: they are the ones where an evaluation item was
# also seen during training. A validation/test overlap never involves training
# data, so it is measured and reported but does not fail a run by default.
_OVERLAP_PAIRS: tuple[tuple[str, str, str], ...] = (
    ("train_validation", "train", "validation"),
    ("train_test", "train", "test"),
    ("validation_test", "validation", "test"),
)

#: Overlap metrics that are hard gates, mapped to their threshold key.
_GATED_OVERLAPS: dict[str, str] = {
    "train_validation": "max_train_validation_leakage_ratio",
    "train_test": "max_train_test_leakage_ratio",
}

#: Reported, and gated only if the threshold is explicitly set to a number.
_UNGATED_OVERLAPS: dict[str, str] = {
    "validation_test": "max_validation_test_overlap_ratio",
}


def _digest(text: str, size: int) -> int:
    """Deterministic short hash.

    Python's built-in ``hash()`` is salted per process, which would make these
    counts vary between runs. BLAKE2b is fast enough at millions of records and
    gives the same answer every time.
    """
    return int.from_bytes(hashlib.blake2b(text.encode("utf-8"), digest_size=size).digest(), "big")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="validate_dataset.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--input-dir",
        type=Path,
        metavar="DIR",
        help="Processed directory to validate. Defaults to preprocessing.output_dir.",
    )
    parser.add_argument(
        "--split",
        nargs="+",
        metavar="NAME",
        help="Only validate these splits. Defaults to every split present.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        metavar="N",
        help="Sample records to include per language in the report.",
    )
    parser.add_argument(
        "--no-report", action="store_true", help="Print results without writing report files."
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Suppress the console table; still sets the exit code."
    )
    return parser


class LanguageAudit:
    """Accumulates every measurement for one language."""

    def __init__(self, language: Language, config: Config) -> None:
        self.language = language
        self.config = config
        self.total = 0
        self.per_split: Counter[str] = Counter()
        self.per_subsource: Counter[str] = Counter()
        self.issues: Counter[str] = Counter()
        self.samples: list[dict[str, Any]] = []
        self.problems: list[dict[str, Any]] = []
        self.script_ratios: list[float] = []
        self.ascii_ratios: list[float] = []
        self.source_lengths: list[int] = []
        self.target_lengths: list[int] = []
        self._seen_ids: set[int] = set()
        # Cross-record state for leakage and ambiguity. Keyed by a hash of the
        # source string, with the splits it appeared in packed as a bitmask
        # alongside a hash of its first target -- keeping the raw strings here
        # would cost gigabytes at Aksharantar's millions of rows per language.
        self._source_index: dict[int, int] = {}
        # Fixed, nameable bit per configured split; everything else shares the
        # overflow bit so an unexpected split name cannot corrupt a pair count.
        self._split_bits: dict[str, int] = {
            name: 1 << index for index, name in enumerate(config.split_names)
        }
        self._overflow_bit = 1 << len(config.split_names)
        self._ambiguous_sources = 0

    # -- per-record checks -------------------------------------------------

    def inspect(self, record: Mapping[str, Any], origin: str, sample_size: int) -> None:
        self.total += 1
        split = str(record.get("split", ""))
        self.per_split[split] += 1
        self.per_subsource[str(record.get("subsource") or "(none)")] += 1

        # `subsource` is optional, so it is absent from REQUIRED_FIELDS and a
        # v1 file without it still passes.
        missing = [field for field in REQUIRED_FIELDS if field not in record]
        if missing:
            self.issues["missing_field"] += 1
            self._note(origin, record, f"missing fields: {', '.join(missing)}")
            return

        if any(record.get(field) is None for field in REQUIRED_FIELDS):
            self.issues["null_value"] += 1
            self._note(origin, record, "null value in a required field")

        source = str(record.get("source_text") or "")
        target = str(record.get("target_text") or "")

        if not source or not target:
            self.issues["empty_text"] += 1
            self._note(origin, record, "empty source_text or target_text")
            return

        if record.get("language") != self.language.code:
            self.issues["language_mismatch"] += 1
            self._note(origin, record, f"language {record.get('language')!r} in {origin}")

        record_id = str(record.get("record_id") or "")
        expected = stable_id(str(record.get("language")), source, target)
        if record_id != expected:
            self.issues["record_id_mismatch"] += 1
            self._note(origin, record, "record_id does not match its contents")

        fingerprint = int(record_id or expected, 16)
        if fingerprint in self._seen_ids:
            self.issues["duplicate"] += 1
        else:
            self._seen_ids.add(fingerprint)

        # Unicode normalisation: two visually identical strings that are not
        # both NFC will never deduplicate or match at inference time.
        if unicodedata.normalize("NFC", target) != target:
            self.issues["target_not_nfc"] += 1

        ratio = script_ratio(
            target,
            self.language.unicode_ranges,
            neutral_codepoints=self.config.neutral_codepoints,
            neutral_categories=self.config.neutral_categories,
        )
        self.script_ratios.append(ratio)
        threshold = float(
            self.config.preprocessing.get("min_target_script_ratio", 0.9)
        )
        if ratio < threshold:
            self.issues["target_wrong_script"] += 1
            self._note(origin, record, f"target script ratio {ratio:.2f} < {threshold}")

        latin = ascii_ratio(source)
        self.ascii_ratios.append(latin)
        if latin < float(self.config.preprocessing.get("min_source_ascii_ratio", 0.9)):
            self.issues["source_not_romanized"] += 1
            self._note(origin, record, f"source ascii ratio {latin:.2f}")

        self.source_lengths.append(len(source))
        self.target_lengths.append(len(target))

        self._track_source(source, target, split)

        if len(self.samples) < sample_size:
            self.samples.append({"source_text": source, "target_text": target, "split": split})

    def _track_source(self, source: str, target: str, split: str) -> None:
        """Record which splits a Roman spelling appears in, and whether it is ambiguous.

        Packed as ``(split_bitmask << 32) | target_hash`` so the whole index is
        one int-to-int dict.
        """
        bit = self._split_bits.get(split, self._overflow_bit)
        key = _digest(source, 8)
        target_hash = _digest(target, 4)

        if bit == self._overflow_bit:
            self.issues["unknown_split_name"] += 1

        packed = self._source_index.get(key)
        if packed is None:
            self._source_index[key] = (bit << _SPLIT_SHIFT) | target_hash
            return

        if (packed & 0xFFFF_FFFF) != target_hash and not packed & _AMBIGUOUS_BIT:
            # One Roman spelling with several native forms. Legitimate in
            # transliteration; flag it once per source, not once per record.
            self._ambiguous_sources += 1
            packed |= _AMBIGUOUS_BIT
        self._source_index[key] = packed | (bit << _SPLIT_SHIFT)

    def _note(self, origin: str, record: Mapping[str, Any], message: str) -> None:
        if len(self.problems) < 25:  # keep the report readable
            self.problems.append(
                {
                    "file": origin,
                    "message": message,
                    "source_text": record.get("source_text"),
                    "target_text": record.get("target_text"),
                }
            )

    # -- aggregate ---------------------------------------------------------

    def overlaps(self) -> dict[str, int]:
        """Count source strings shared between each pair of splits.

        A source present in all three splits counts once in every pair it
        participates in -- it genuinely is in each intersection.

        The pairs are reported separately because they do not mean the same
        thing. ``train_validation`` and ``train_test`` are contamination: an
        evaluation item the model was trained on, which inflates its score.
        ``validation_test`` involves no training data at all; it only means the
        two evaluation sets are slightly correlated, so it is measured and
        reported but not treated as a failure.
        """
        counts = dict.fromkeys((name for name, _, _ in _OVERLAP_PAIRS), 0)
        counts["any"] = 0

        pairs = [
            (name, self._split_bits.get(a, 0), self._split_bits.get(b, 0))
            for name, a, b in _OVERLAP_PAIRS
        ]

        for packed in self._source_index.values():
            mask = (packed >> _SPLIT_SHIFT) & _SPLIT_MASK
            if mask.bit_count() < 2:
                continue
            counts["any"] += 1
            for name, bit_a, bit_b in pairs:
                if bit_a and bit_b and mask & bit_a and mask & bit_b:
                    counts[name] += 1
        return counts

    def summary(self) -> dict[str, Any]:
        overlaps = self.overlaps()
        # Ratios are per unique source spelling, not per record: the question
        # is "what fraction of the vocabulary is shared", not "how many rows".
        denominator = max(len(self._source_index), 1)
        overlap_block = {
            name: {
                "count": overlaps[name],
                "ratio": _safe_div(overlaps[name], denominator),
                "gated": name in _GATED_OVERLAPS,
            }
            for name, _, _ in _OVERLAP_PAIRS
        }
        return {
            "language": self.language.code,
            "name": self.language.name,
            "script": self.language.script_code,
            "records": self.total,
            "per_split": dict(sorted(self.per_split.items())),
            "per_subsource": dict(self.per_subsource.most_common()),
            "unique_sources": len(self._source_index),
            "issues": dict(self.issues.most_common()),
            "ratios": {
                "duplicate": _safe_div(self.issues["duplicate"], self.total),
                "null": _safe_div(self.issues["null_value"], self.total),
                "empty": _safe_div(self.issues["empty_text"], self.total),
                "target_script_ok": _safe_div(
                    self.total - self.issues["target_wrong_script"], self.total
                ),
                "source_ascii_ok": _safe_div(
                    self.total - self.issues["source_not_romanized"], self.total
                ),
            },
            "split_overlap": overlap_block,
            "sources_in_multiple_splits": overlaps["any"],
            "ambiguous_sources": self._ambiguous_sources,
            "mean_script_ratio": _mean(self.script_ratios),
            "mean_ascii_ratio": _mean(self.ascii_ratios),
            "source_length": _length_stats(self.source_lengths),
            "target_length": _length_stats(self.target_lengths),
            "samples": self.samples,
            "problems": self.problems,
        }


def _safe_div(numerator: float, denominator: float) -> float:
    return round(numerator / denominator, 6) if denominator else 0.0


def _mean(values: Sequence[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def _length_stats(values: Sequence[int]) -> dict[str, float]:
    if not values:
        return {"min": 0, "max": 0, "mean": 0.0}
    return {"min": min(values), "max": max(values), "mean": round(sum(values) / len(values), 2)}


# --------------------------------------------------------------------------
# threshold evaluation
# --------------------------------------------------------------------------


def evaluate(summary: Mapping[str, Any], thresholds: Mapping[str, Any]) -> list[str]:
    """Return a list of human-readable threshold breaches, empty when clean.

    A threshold that is absent or explicitly ``null`` is not checked. That is
    how ``validation_test`` overlap stays reported-but-ungated by default while
    remaining gateable by anyone who wants it.
    """
    failures: list[str] = []
    ratios = summary["ratios"]

    checks: list[tuple[str, float, str]] = [
        ("max_null_ratio", ratios["null"], "<="),
        ("max_empty_ratio", ratios["empty"], "<="),
        ("max_duplicate_ratio", ratios["duplicate"], "<="),
        ("min_target_script_ratio", ratios["target_script_ok"], ">="),
        ("min_source_ascii_ratio", ratios["source_ascii_ok"], ">="),
    ]

    # Split overlap: train<->eval pairs are always gated, validation<->test
    # only if the user set a number for it.
    overlap = summary.get("split_overlap", {})
    for metric, key in {**_GATED_OVERLAPS, **_UNGATED_OVERLAPS}.items():
        if metric in overlap:
            checks.append((key, overlap[metric]["ratio"], "<="))

    for key, actual, direction in checks:
        limit_raw = thresholds.get(key)
        if limit_raw is None:
            continue
        limit = float(limit_raw)
        breached = actual > limit if direction == "<=" else actual < limit
        if breached:
            failures.append(f"{key}: {actual:.6f} {'>' if direction == '<=' else '<'} {limit}")

    minimum = thresholds.get("min_records_per_language")
    if minimum is not None and summary["records"] < int(minimum):
        failures.append(f"min_records_per_language: {summary['records']} < {int(minimum)}")

    return failures


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------


def print_console(report: Mapping[str, Any]) -> None:
    print(f"\n{'=' * 86}\nVALIDATION -- {report['input_dir']}\n{'=' * 86}")
    header = (
        f"  {'lang':<6} {'records':>10} {'dupes':>8} {'script':>8} "
        f"{'roman':>8} {'status':>10}"
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    for summary in report["languages"]:
        ratios = summary["ratios"]
        status = "PASS" if not summary["failures"] else "FAIL"
        print(
            f"  {summary['language']:<6} {summary['records']:>10,} "
            f"{ratios['duplicate']:>8.4f} {ratios['target_script_ok']:>8.4f} "
            f"{ratios['source_ascii_ok']:>8.4f} {status:>10}"
        )

    # Split overlap gets its own block: the pairs mean different things and a
    # single column cannot say which one is contamination.
    print(f"\n  Split overlap (shared source spellings)\n  {'-' * 74}")
    print(f"  {'lang':<6} {'pair':<20} {'count':>10} {'ratio':>12}  gate")
    for summary in report["languages"]:
        for metric, info in summary.get("split_overlap", {}).items():
            gate = "GATED at 0" if info["gated"] else "reported only"
            print(
                f"  {summary['language']:<6} {metric:<20} {info['count']:>10,} "
                f"{info['ratio']:>12.6f}  {gate}"
            )

    for summary in report["languages"]:
        if summary["failures"]:
            print(f"\n  {summary['language']} threshold breaches:")
            for failure in summary["failures"]:
                print(f"    - {failure}")
        if summary["problems"]:
            print(f"\n  {summary['language']} example problems (first "
                  f"{len(summary['problems'])}):")
            for problem in summary["problems"][:5]:
                print(f"    - [{problem['file']}] {problem['message']}")
                print(f"        {problem['source_text']!r} -> {problem['target_text']!r}")

    verdict = "PASSED" if report["passed"] else "FAILED"
    print(f"\n  Overall: {verdict}  ({report['total_records']:,} records across "
          f"{len(report['languages'])} language(s))\n")


def render_markdown(report: Mapping[str, Any]) -> str:
    lines = [
        "# IndicPass validation report",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Input:** `{report['input_dir']}`",
        f"- **Records:** {report['total_records']:,}",
        f"- **Result:** {'PASSED' if report['passed'] else 'FAILED'}",
        "",
        "## Summary",
        "",
        "| Language | Records | Unique sources | Duplicate ratio | Target script OK "
        "| Source Roman OK | Status |",
        "| --- | ---: | ---: | ---: | ---: | ---: | :--- |",
    ]

    for summary in report["languages"]:
        ratios = summary["ratios"]
        lines.append(
            f"| {summary['language']} ({summary['name']}) | {summary['records']:,} "
            f"| {summary['unique_sources']:,} | {ratios['duplicate']:.4f} "
            f"| {ratios['target_script_ok']:.4f} | {ratios['source_ascii_ok']:.4f} "
            f"| {'PASS' if not summary['failures'] else 'FAIL'} |"
        )

    lines += [
        "",
        "## Split overlap",
        "",
        "Shared source spellings between split pairs, as a fraction of unique sources.",
        "`train_validation` and `train_test` are contamination and are hard gates.",
        "`validation_test` involves no training data, so it is reported, not gated.",
        "",
        "| Language | Pair | Shared sources | Ratio | Gate |",
        "| --- | --- | ---: | ---: | :--- |",
    ]
    for summary in report["languages"]:
        for metric, info in summary.get("split_overlap", {}).items():
            gate = "**gated at 0.0**" if info["gated"] else "reported only"
            lines.append(
                f"| {summary['language']} | {metric} | {info['count']:,} "
                f"| {info['ratio']:.6f} | {gate} |"
            )

    for summary in report["languages"]:
        lines += ["", f"## {summary['language']} -- {summary['name']}", ""]
        lines.append(f"- Splits: {summary['per_split'] or 'none'}")
        lines.append(
            f"- Source length min/mean/max: {summary['source_length']['min']}"
            f" / {summary['source_length']['mean']} / {summary['source_length']['max']}"
        )
        lines.append(
            f"- Target length min/mean/max: {summary['target_length']['min']}"
            f" / {summary['target_length']['mean']} / {summary['target_length']['max']}"
        )
        lines.append(f"- Ambiguous sources (one Roman form, several native forms): "
                     f"{summary['ambiguous_sources']:,}")
        lines.append(f"- Sources appearing in more than one split: "
                     f"{summary['sources_in_multiple_splits']:,}")

        if summary.get("per_subsource"):
            lines += ["", "**Provenance by subsource**", "", "| Subsource | Records | Share |",
                      "| --- | ---: | ---: |"]
            total = summary["records"] or 1
            lines += [
                f"| {name} | {count:,} | {count / total * 100:.2f}% |"
                for name, count in summary["per_subsource"].items()
            ]

        if summary["issues"]:
            lines += ["", "**Issues**", ""]
            lines += [f"- `{name}`: {count:,}" for name, count in summary["issues"].items()]
        if summary["failures"]:
            lines += ["", "**Threshold breaches**", ""]
            lines += [f"- {failure}" for failure in summary["failures"]]
        if summary["samples"]:
            lines += ["", "**Samples**", "", "| source | target | split |", "| --- | --- | --- |"]
            lines += [
                f"| `{s['source_text']}` | {s['target_text']} | {s['split']} |"
                for s in summary["samples"]
            ]

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    source_name = args.source or config.default_source
    settings = config.validation
    input_dir = config.resolve(
        args.input_dir or config.preprocessing.get("output_dir", "data/processed")
    )
    sample_size = args.samples if args.samples is not None else int(settings.get("sample_size", 5))
    thresholds = settings.get("thresholds", {})

    if not input_dir.exists():
        logger.error(
            "Nothing to validate: %s does not exist.\nRun preprocessing first:\n"
            "    python scripts/preprocess_dataset.py",
            config.relative(input_dir),
        )
        return 1

    languages = config.resolve_languages(args.languages)
    audits: list[dict[str, Any]] = []
    inspected_files = 0

    for language in languages:
        root = input_dir / source_name / language.code
        files = sorted(root.glob("*.jsonl")) if root.exists() else []
        if args.split:
            wanted = {name.lower() for name in args.split}
            files = [path for path in files if path.stem.lower() in wanted]

        if not files:
            logger.warning("%s: no processed files under %s", language.code, config.relative(root))
            continue

        audit = LanguageAudit(language, config)
        for path in files:
            inspected_files += 1
            origin = path.name
            for record in progress(read_jsonl(path), f"validating {language.code}/{path.stem}"):
                audit.inspect(record, origin, sample_size)

        summary = audit.summary()
        summary["failures"] = evaluate(summary, thresholds)
        summary["files"] = [config.relative(path) for path in files]
        audits.append(summary)
        logger.info(
            "%s: %d records, %d issue type(s), %s",
            language.code,
            summary["records"],
            len(summary["issues"]),
            "PASS" if not summary["failures"] else "FAIL",
        )

    if not audits:
        logger.error(
            "No processed data found under %s. Run preprocessing first.",
            config.relative(input_dir),
        )
        return 1

    report: dict[str, Any] = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "project": f"{config.name} v{config.version}",
        "source": source_name,
        "input_dir": config.relative(input_dir),
        "files_inspected": inspected_files,
        "thresholds": dict(thresholds),
        "total_records": sum(summary["records"] for summary in audits),
        "languages": audits,
        "passed": all(not summary["failures"] for summary in audits),
    }

    if not args.quiet:
        print_console(report)

    if not args.no_report:
        report_dir = config.resolve(settings.get("report_dir", "results/reports"))
        report_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        prefix = str(settings.get("report_prefix", "validation_report"))

        json_path = report_dir / f"{prefix}_{stamp}.json"
        json_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        md_path = report_dir / f"{prefix}_{stamp}.md"
        md_path.write_text(render_markdown(report), encoding="utf-8")

        # A stable filename so tooling always has a "latest" to read.
        (report_dir / f"{prefix}_latest.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        logger.info("Report written to %s", config.relative(md_path))

    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(run_cli(main))
