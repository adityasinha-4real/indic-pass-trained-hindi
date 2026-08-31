#!/usr/bin/env python
"""Turn raw downloads into standardized, deduplicated JSONL under ``data/processed/``.

Raw data is never touched. Everything under ``data/raw/`` is opened read-only;
all output goes to ``data/processed/<source>/<language>/<split>.jsonl``.

The run is reproducible: given the same raw files and the same
``config/dataset.yaml``, the output is byte-identical. Two design choices make
that true --

* Records are identified by a content hash, not by position in a file.
* Splits are assigned from that hash, not by shuffling, so the partition does
  not depend on file order and stays stable when new records are appended.

Every dropped record is counted by reason and reported, so silent data loss
shows up as a number instead of a mystery.

Examples
--------
    python scripts/preprocess_dataset.py --dry-run
    python scripts/preprocess_dataset.py --languages hin tam
    python scripts/preprocess_dataset.py --limit 5000 --force
"""

from __future__ import annotations

import argparse
import csv
import io
import itertools
import json
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import TracebackType
from typing import Any, Iterator, Mapping, Sequence, TextIO

import _bootstrap  # noqa: F401  -- puts src/ on sys.path

from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config, Language
from indicpass.hub import write_manifest
from indicpass.logging_utils import get_logger, progress
from indicpass.records import Record, assign_split, stable_id
from indicpass.script_utils import ascii_ratio, collapse_whitespace, normalize, script_ratio

SCRIPT = "preprocess_dataset"

_RECORD_SUFFIXES = {".json", ".jsonl", ".ndjson", ".csv", ".tsv"}


#: Rejected records kept per drop reason, so a summary can show what was lost
#: rather than only how much.
_SAMPLES_PER_REASON = 4


@dataclass
class LanguageStats:
    """Why records survived or did not, for one language."""

    read: int = 0
    written: int = 0
    dropped: Counter[str] = field(default_factory=Counter)
    per_split: Counter[str] = field(default_factory=Counter)
    per_subsource: Counter[str] = field(default_factory=Counter)
    dropped_per_subsource: Counter[str] = field(default_factory=Counter)
    samples: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    files: list[str] = field(default_factory=list)

    def drop(self, reason: str, raw: Mapping[str, Any] | None = None) -> None:
        self.dropped[reason] += 1
        if raw is None:
            return
        kept = self.samples.setdefault(reason, [])
        if len(kept) < _SAMPLES_PER_REASON:
            kept.append({str(k): v for k, v in list(raw.items())[:6]})

    def drop_rate(self, reason: str) -> float:
        return self.dropped[reason] / self.read if self.read else 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "read": self.read,
            "written": self.written,
            "dropped_total": sum(self.dropped.values()),
            "dropped_by_reason": dict(self.dropped.most_common()),
            "dropped_pct_by_reason": {
                reason: round(self.drop_rate(reason) * 100, 4)
                for reason, _ in self.dropped.most_common()
            },
            "per_split": dict(sorted(self.per_split.items())),
            "per_subsource": dict(self.per_subsource.most_common()),
            "dropped_per_subsource": dict(self.dropped_per_subsource.most_common()),
            "source_files": self.files,
        }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="preprocess_dataset.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--input-dir",
        type=Path,
        metavar="DIR",
        help="Raw directory to read. Defaults to the source's raw_dir.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        metavar="DIR",
        help="Where to write processed JSONL. Defaults to preprocessing.output_dir.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        metavar="N",
        help="Keep at most N records per language. Useful for a fast smoke run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate everything, report the stats, write nothing.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing processed files instead of refusing.",
    )
    return parser


# --------------------------------------------------------------------------
# raw record iteration
# --------------------------------------------------------------------------


def find_language_files(root: Path, language: Language, source_name: str) -> list[Path]:
    """Locate the raw files belonging to one language.

    Matches on the language's dataset code appearing as a path component or a
    filename token, which covers both ``hin/hin_train.json`` and ``hin.zip``.

    An archive and its own extracted contents both match, which would read
    every record twice. When ``hin.zip`` has already been unpacked to
    ``extracted/hin/``, the archive is dropped in favour of the loose files.
    """
    code = language.dataset_code(source_name).lower()
    if not root.exists():
        return []

    matches: list[Path] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in _RECORD_SUFFIXES | {".zip"}:
            continue

        relative = path.relative_to(root)
        # Skip tool state such as the Hugging Face .cache/ written next to the
        # download; it is not dataset content.
        if any(part.startswith(".") for part in relative.parts):
            continue

        parts = [part.lower() for part in relative.parts]
        tokens = {token for part in parts for token in _tokenize(part)}
        if code in tokens or code in parts:
            matches.append(path)

    return _drop_extracted_archives(matches)


def _drop_extracted_archives(matches: list[Path]) -> list[Path]:
    """Remove archives whose extracted contents are already in *matches*."""
    loose = {path for path in matches if path.suffix.lower() != ".zip"}
    if not loose:
        return matches

    kept: list[Path] = []
    for path in matches:
        if path.suffix.lower() == ".zip" and any(
            path.stem.lower() in {part.lower() for part in other.parts} for other in loose
        ):
            continue
        kept.append(path)
    return kept


def _tokenize(name: str) -> set[str]:
    """Split a filename into comparable tokens: ``hin_train.json`` -> {hin, train}."""
    stem = Path(name).stem.lower()
    for separator in ("_", "-", "."):
        stem = stem.replace(separator, " ")
    return set(stem.split())


def iter_raw_records(path: Path) -> Iterator[tuple[Mapping[str, Any], str]]:
    """Yield ``(record, origin)`` pairs from a raw file, without extracting archives."""
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as bundle:
            members = sorted(
                (m for m in bundle.infolist() if not m.is_dir()),
                key=lambda m: m.filename,
            )
            for member in members:
                if Path(member.filename).suffix.lower() not in _RECORD_SUFFIXES:
                    continue
                with bundle.open(member) as handle:
                    for record in _iter_stream(handle, member.filename):
                        yield record, f"{path.name}!{member.filename}"
        return

    with path.open("rb") as handle:
        for record in _iter_stream(handle, path.name):
            yield record, path.name


def _iter_stream(handle: Any, name: str) -> Iterator[Mapping[str, Any]]:
    text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline="")
    suffix = Path(name).suffix.lower()

    if suffix in {".csv", ".tsv"}:
        yield from csv.DictReader(text, delimiter="\t" if suffix == ".tsv" else ",")
        return

    first = text.readline()
    if not first.strip():
        return

    if first.lstrip().startswith("["):
        payload = json.loads(first + text.read())
        for item in payload if isinstance(payload, list) else [payload]:
            if isinstance(item, dict):
                yield item
        return

    for line in itertools.chain((first,), text):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            item = json.loads(stripped)
        except json.JSONDecodeError:
            continue  # counted as malformed by the caller's read/write delta
        if isinstance(item, dict):
            yield item


# --------------------------------------------------------------------------
# field mapping and cleaning
# --------------------------------------------------------------------------


def pick_field(record: Mapping[str, Any], candidates: Sequence[str]) -> str | None:
    """First present, non-empty value among *candidates*, matched case-insensitively."""
    lowered = {str(key).strip().lower(): value for key, value in record.items()}
    for candidate in candidates:
        value = lowered.get(candidate.strip().lower())
        if value is not None and str(value).strip():
            return str(value)
    return None


def detect_split(origin: str, markers: Mapping[str, Sequence[str]]) -> str | None:
    """Infer a split name from the file it came from, e.g. ``hin_valid.json``."""
    tokens = _tokenize(origin.replace("!", " ").replace("/", " "))
    for split, needles in markers.items():
        if any(str(needle).lower() in tokens for needle in needles):
            return split
    return None


def clean(text: str, options: Mapping[str, Any], *, lowercase: bool) -> str:
    result = normalize(text, str(options.get("unicode_normalization", "NFC")))
    if options.get("collapse_internal_whitespace", True):
        result = collapse_whitespace(result)
    elif options.get("strip_whitespace", True):
        result = result.strip()
    return result.lower() if lowercase else result


def build_record(
    raw: Mapping[str, Any],
    origin: str,
    language: Language,
    config: Config,
    source_name: str,
    source_cfg: Mapping[str, Any],
    options: Mapping[str, Any],
    stats: LanguageStats,
) -> Record | None:
    """Map one upstream record onto the standard schema, or drop it with a reason."""
    field_map = source_cfg.get("field_map", {})
    raw_source = pick_field(raw, field_map.get("source_text", ["source_text"]))
    raw_target = pick_field(raw, field_map.get("target_text", ["target_text"]))

    if raw_source is None or raw_target is None:
        stats.drop("missing_field", raw)
        return None

    source_text = clean(raw_source, options, lowercase=bool(options.get("lowercase_source", True)))
    target_text = clean(raw_target, options, lowercase=bool(options.get("lowercase_target", False)))
    subsource = extract_subsource(raw, field_map, raw_source, raw_target)

    if options.get("drop_empty", True) and (not source_text or not target_text):
        stats.drop("empty_after_cleaning", raw)
        stats.dropped_per_subsource[subsource or "(none)"] += 1
        return None

    if not _length_ok(source_text, options, "source"):
        stats.drop("source_length", raw)
        stats.dropped_per_subsource[subsource or "(none)"] += 1
        return None
    if not _length_ok(target_text, options, "target"):
        stats.drop("target_length", raw)
        stats.dropped_per_subsource[subsource or "(none)"] += 1
        return None

    if options.get("require_ascii_source", True):
        threshold = float(options.get("min_source_ascii_ratio", 0.9))
        if ascii_ratio(source_text) < threshold:
            stats.drop("source_not_romanized", raw)
            stats.dropped_per_subsource[subsource or "(none)"] += 1
            return None

    if options.get("require_native_script_target", True):
        threshold = float(options.get("min_target_script_ratio", 0.9))
        ratio = script_ratio(
            target_text,
            language.unicode_ranges,
            neutral_codepoints=config.neutral_codepoints,
            neutral_categories=config.neutral_categories,
        )
        if ratio < threshold:
            stats.drop("target_wrong_script", raw)
            stats.dropped_per_subsource[subsource or "(none)"] += 1
            return None

    split = _resolve_split(origin, language, source_text, target_text, config, source_cfg)

    return Record(
        language=language.code,
        script=language.script_code,
        source_text=source_text,
        target_text=target_text,
        dataset_source=source_name,
        subsource=subsource,
        split=split,
    )


def extract_subsource(
    raw: Mapping[str, Any],
    field_map: Mapping[str, Any],
    raw_source: str,
    raw_target: str,
) -> str:
    """Pull the sub-corpus label out of a raw record.

    Aksharantar names this column ``source``, which is also a candidate for
    ``source_text``. If the value we get back is just the text again, the
    column means "the text" rather than "where it came from", so it is
    discarded instead of being recorded as bogus provenance.
    """
    value = pick_field(raw, field_map.get("subsource", []))
    if value is None:
        return ""
    value = value.strip()
    if value in {raw_source.strip(), raw_target.strip()}:
        return ""
    return value


def _length_ok(text: str, options: Mapping[str, Any], side: str) -> bool:
    minimum = options.get(f"min_{side}_length")
    maximum = options.get(f"max_{side}_length")
    if minimum is not None and len(text) < int(minimum):
        return False
    return not (maximum is not None and len(text) > int(maximum))


def _resolve_split(
    origin: str,
    language: Language,
    source_text: str,
    target_text: str,
    config: Config,
    source_cfg: Mapping[str, Any],
) -> str:
    splits = config.splits
    if splits.get("use_native_splits", True):
        native = detect_split(origin, source_cfg.get("split_markers", {}))
        if native:
            return native
    ratios = {k: float(v) for k, v in (splits.get("ratios") or {}).items()}
    if not ratios:
        return "train"
    return assign_split(stable_id(language.code, source_text, target_text), ratios)


# --------------------------------------------------------------------------
# per-language processing
# --------------------------------------------------------------------------


class SplitWriter:
    """Streams records straight to one JSONL file per split.

    Buffering a whole language in memory is not an option -- Aksharantar's
    Hindi portion alone runs into millions of pairs -- so files are opened
    lazily on the first record for a split and written as the input is read.
    Empty splits therefore never create an empty file.
    """

    def __init__(self, base: Path, *, enabled: bool = True) -> None:
        self.base = base
        self.enabled = enabled
        self._handles: dict[str, TextIO] = {}
        self.counts: Counter[str] = Counter()

    def write(self, record: Record) -> None:
        self.counts[record.split] += 1
        if not self.enabled:
            return
        handle = self._handles.get(record.split)
        if handle is None:
            path = self.base / f"{record.split}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            handle = path.open("w", encoding="utf-8", newline="\n")
            self._handles[record.split] = handle
        handle.write(json.dumps(record.to_dict(), ensure_ascii=False))
        handle.write("\n")

    @property
    def paths(self) -> list[Path]:
        return [self.base / f"{split}.jsonl" for split in sorted(self._handles)]

    def __enter__(self) -> "SplitWriter":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        for handle in self._handles.values():
            handle.close()


def process_language(
    language: Language,
    config: Config,
    source_name: str,
    source_cfg: Mapping[str, Any],
    input_dir: Path,
    output_dir: Path,
    args: argparse.Namespace,
) -> LanguageStats:
    logger = get_logger(SCRIPT)
    options = config.preprocessing
    stats = LanguageStats()

    files = find_language_files(input_dir, language, source_name)
    if not files:
        logger.warning(
            "%s: no raw files found under %s -- skipping.",
            language.code,
            config.relative(input_dir),
        )
        return stats
    stats.files = [config.relative(path) for path in files]
    logger.info("%s: reading %d raw file(s)", language.code, len(files))

    destination = output_dir / source_name / language.code
    if not args.dry_run and not args.force:
        existing = [p for p in destination.glob("*.jsonl") if p.is_file()]
        if existing:
            raise FileExistsError(
                f"{config.relative(destination)} already holds "
                f"{len(existing)} processed file(s). Pass --force to overwrite."
            )

    limit = args.limit if args.limit is not None else options.get("max_records_per_language")
    limit = int(limit) if limit else None
    dedup = bool(options.get("drop_duplicates", True))

    # Store the hash as an int, not the hex string: at several million records
    # the difference in resident memory is hundreds of megabytes.
    seen: set[int] = set()

    with SplitWriter(destination, enabled=not args.dry_run) as writer:
        for path in files:
            for raw, origin in progress(iter_raw_records(path), f"{language.code} {path.name}"):
                stats.read += 1
                record = build_record(
                    raw, origin, language, config, source_name, source_cfg, options, stats
                )
                if record is None:
                    continue
                if dedup:
                    fingerprint = int(record.record_id, 16)
                    if fingerprint in seen:
                        stats.drop("duplicate", raw)
                        stats.dropped_per_subsource[record.subsource or "(none)"] += 1
                        continue
                    seen.add(fingerprint)

                writer.write(record)
                stats.written += 1
                stats.per_split[record.split] += 1
                stats.per_subsource[record.subsource or "(none)"] += 1

                if limit is not None and stats.written >= limit:
                    logger.info("%s: reached the %d-record limit", language.code, limit)
                    break
            if limit is not None and stats.written >= limit:
                break

        written_paths = writer.paths

    for path in written_paths:
        logger.info(
            "%s: wrote %7d -> %s",
            language.code,
            stats.per_split.get(path.stem, 0),
            config.relative(path),
        )
    return stats


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    source_name = args.source or config.default_source
    source_cfg = config.source(source_name)
    input_dir = config.resolve(args.input_dir or source_cfg["raw_dir"])
    output_dir = config.resolve(
        args.output_dir or config.preprocessing.get("output_dir", "data/processed")
    )

    if not input_dir.exists() or not any(input_dir.rglob("*")):
        logger.error(
            "No raw data in %s.\nDownload it first:\n"
            "    python scripts/download_datasets.py --plan-only",
            config.relative(input_dir),
        )
        return 1

    languages = config.resolve_languages(args.languages)
    logger.info(
        "Preprocessing %s from %s%s",
        ", ".join(language.code for language in languages),
        source_name,
        " (dry run -- nothing will be written)" if args.dry_run else "",
    )

    results: dict[str, LanguageStats] = {}
    for language in languages:
        results[language.code] = process_language(
            language, config, source_name, source_cfg, input_dir, output_dir, args
        )

    _print_summary(results, config, dry_run=args.dry_run)

    total_written = sum(stats.written for stats in results.values())
    if total_written == 0:
        logger.error("No records survived preprocessing. Check the drop reasons above.")
        return 1

    if not args.dry_run:
        manifest = write_manifest(
            output_dir / "preprocess_manifest.json",
            {
                "source": source_name,
                "input_dir": config.relative(input_dir),
                "output_dir": config.relative(output_dir),
                "languages": {code: stats.as_dict() for code, stats in results.items()},
                "preprocessing": config.preprocessing,
                "splits": config.splits,
                "total_written": total_written,
            },
        )
        logger.info("Manifest written to %s", config.relative(manifest))
        logger.info("Next: python scripts/validate_dataset.py")

    return 0


def _print_summary(
    results: Mapping[str, LanguageStats],
    config: Config,
    *,
    dry_run: bool = False,
    show_samples: bool = True,
) -> None:
    splits = config.split_names
    title = "PREPROCESSING DRY RUN (nothing written)" if dry_run else "PREPROCESSING SUMMARY"
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")

    # -- discovered / accepted, and the split breakdown --------------------
    header = f"  {'lang':<6} {'read':>11} {'kept':>11} {'kept%':>7} {'dropped':>10}  " + "".join(
        f"{name[:10]:>11}" for name in splits
    )
    print(header)
    print("  " + "-" * (len(header) - 2))

    totals: Counter[str] = Counter()
    for code, stats in results.items():
        dropped = sum(stats.dropped.values())
        totals["read"] += stats.read
        totals["written"] += stats.written
        totals["dropped"] += dropped
        kept_pct = (stats.written / stats.read * 100) if stats.read else 0.0
        row = (
            f"  {code:<6} {stats.read:>11,} {stats.written:>11,} "
            f"{kept_pct:>6.2f}% {dropped:>10,}  "
        )
        row += "".join(f"{stats.per_split.get(name, 0):>11,}" for name in splits)
        print(row)

    if len(results) > 1:
        print("  " + "-" * (len(header) - 2))
        overall = (totals["written"] / totals["read"] * 100) if totals["read"] else 0.0
        print(
            f"  {'ALL':<6} {totals['read']:>11,} {totals['written']:>11,} "
            f"{overall:>6.2f}% {totals['dropped']:>10,}"
        )

    # -- drop reasons, with percentages ------------------------------------
    reasons: Counter[str] = Counter()
    for stats in results.values():
        reasons.update(stats.dropped)

    print(f"\n  Dropped by reason\n  {'-' * 52}")
    if not reasons:
        print("    (none -- every discovered record was accepted)")
    else:
        read_total = totals["read"] or 1
        print(f"    {'reason':<24} {'count':>12} {'% of read':>12}")
        for reason, count in reasons.most_common():
            print(f"    {reason:<24} {count:>12,} {count / read_total * 100:>11.4f}%")
        print(
            f"    {'TOTAL DROPPED':<24} {totals['dropped']:>12,} "
            f"{totals['dropped'] / read_total * 100:>11.4f}%"
        )

    # -- provenance --------------------------------------------------------
    subsources: Counter[str] = Counter()
    dropped_subsources: Counter[str] = Counter()
    for stats in results.values():
        subsources.update(stats.per_subsource)
        dropped_subsources.update(stats.dropped_per_subsource)

    print(f"\n  Accepted by subsource\n  {'-' * 52}")
    if not subsources:
        print("    (none)")
    else:
        kept_total = sum(subsources.values()) or 1
        print(f"    {'subsource':<24} {'kept':>12} {'% of kept':>12} {'dropped':>10}")
        for name, count in subsources.most_common():
            print(
                f"    {name:<24} {count:>12,} {count / kept_total * 100:>11.2f}% "
                f"{dropped_subsources.get(name, 0):>10,}"
            )

    # -- what the dropped records actually looked like ---------------------
    if show_samples:
        printed = False
        for code, stats in results.items():
            for reason, rows in stats.samples.items():
                if not rows:
                    continue
                if not printed:
                    print(f"\n  Representative dropped records\n  {'-' * 74}")
                    printed = True
                print(f"    [{code}] {reason}  ({stats.dropped[reason]:,} total, "
                      f"{stats.drop_rate(reason) * 100:.4f}% of read)")
                for row in rows:
                    rendered = json.dumps(row, ensure_ascii=False)
                    print(f"      {rendered[:150]}{'...' if len(rendered) > 150 else ''}")
    print()


if __name__ == "__main__":
    sys.exit(run_cli(main))
