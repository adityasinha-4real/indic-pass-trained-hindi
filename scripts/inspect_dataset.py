#!/usr/bin/env python
"""Inspect a dataset without modifying it -- remotely on the Hub or locally on disk.

Read-only, always. Local files are opened in binary/text read mode and zip
archives are peeked into without extracting, so this script can be pointed at
``data/raw/`` freely.

Two modes:

``--remote``
    Query the Hugging Face API for repository metadata: revision, licence,
    gating, the full file listing with sizes, and how many bytes the configured
    languages actually account for. Transfers metadata only -- this is how you
    size up Aksharantar before committing to a download.

``--local``
    Walk ``data/raw/``: what files exist, what format they are, how many
    records they hold, what columns they have, and a few real samples.

Examples
--------
    python scripts/inspect_dataset.py --remote
    python scripts/inspect_dataset.py --remote --list-files
    python scripts/inspect_dataset.py --local --samples 3
    python scripts/inspect_dataset.py --remote --json > results/reports/aksharantar.json
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Sequence

import _bootstrap  # noqa: F401  -- puts src/ on sys.path

from indicpass.cli import add_common_arguments, run_cli, startup
from indicpass.config import Config
from indicpass.hub import HubError, RemoteFile, list_remote_files, match_files, repo_metadata
from indicpass.logging_utils import format_bytes

SCRIPT = "inspect_dataset"

# Formats we know how to peek into. Anything else is reported by size only.
_TEXT_SUFFIXES = {".json", ".jsonl", ".ndjson", ".txt", ".csv", ".tsv"}
_MAX_SCAN_BYTES = 64 * 1024 * 1024  # cap full line counts on very large files


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="inspect_dataset.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument("--remote", action="store_true", help="Inspect the Hub repository.")
    parser.add_argument("--local", action="store_true", help="Inspect files under data/raw/.")
    parser.add_argument(
        "--list-files",
        action="store_true",
        help="Print the complete remote file listing rather than a summary.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=3,
        metavar="N",
        help="Sample records to print per local file (default: 3, 0 to disable).",
    )
    parser.add_argument(
        "--path",
        type=Path,
        metavar="DIR",
        help="Directory to inspect in --local mode. Defaults to the source's raw_dir.",
    )
    parser.add_argument(
        "--revision", metavar="SHA", help="Inspect a specific repository revision."
    )
    parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON on stdout instead."
    )
    return parser


# --------------------------------------------------------------------------
# remote inspection
# --------------------------------------------------------------------------


def inspect_remote(config: Config, source_name: str, args: argparse.Namespace) -> dict[str, Any]:
    source = config.source(source_name)
    repo_id = str(source["repo_id"])
    repo_type = str(source.get("repo_type", "dataset"))
    patterns = source.get("match_patterns") or ["*{code}*"]

    metadata = repo_metadata(repo_id, repo_type=repo_type, revision=args.revision)
    files = list_remote_files(
        repo_id, repo_type=repo_type, revision=metadata.get("revision") or args.revision
    )

    total_bytes = sum(entry.size_or_zero for entry in files)
    by_language: dict[str, dict[str, Any]] = {}
    for language in config.resolve_languages(args.languages):
        matched = match_files(files, patterns, language.dataset_code(source_name))
        by_language[language.code] = {
            "name": language.name,
            "dataset_code": language.dataset_code(source_name),
            "file_count": len(matched),
            "bytes": sum(entry.size_or_zero for entry in matched),
            "files": [entry.path for entry in matched],
        }

    return {
        "mode": "remote",
        "source": source_name,
        "metadata": metadata,
        "file_count": len(files),
        "total_bytes": total_bytes,
        "extensions": _extension_summary(files),
        "top_level": _top_level_summary(files),
        "languages": by_language,
        "all_files": (
            [{"path": entry.path, "bytes": entry.size_or_zero} for entry in files]
            if args.list_files
            else None
        ),
    }


def _extension_summary(files: Sequence[RemoteFile]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for entry in files:
        suffix = Path(entry.path).suffix.lower() or "(none)"
        counts[suffix] += 1
        sizes[suffix] += entry.size_or_zero
    return [
        {"extension": suffix, "count": count, "bytes": sizes[suffix]}
        for suffix, count in counts.most_common()
    ]


def _top_level_summary(files: Sequence[RemoteFile]) -> list[dict[str, Any]]:
    """Group the listing by its first path component to reveal the layout."""
    counts: Counter[str] = Counter()
    sizes: Counter[str] = Counter()
    for entry in files:
        parts = entry.path.split("/")
        head = parts[0] if len(parts) > 1 else "(root)"
        counts[head] += 1
        sizes[head] += entry.size_or_zero
    return [
        {"entry": head, "count": count, "bytes": sizes[head]}
        for head, count in sorted(counts.items())
    ]


def print_remote(report: dict[str, Any], config: Config, list_files: bool) -> None:
    meta = report["metadata"]
    print(f"\n{'=' * 78}")
    print(f"REMOTE  {meta['repo_id']}  ({report['source']})")
    print(f"{'=' * 78}")
    print(f"  revision       {meta['revision']}")
    print(f"  last modified  {meta['last_modified']}")
    print(f"  license        {meta.get('license') or 'not declared in card'}")
    print(f"  gated          {meta.get('gated')}")
    print(f"  downloads      {meta.get('downloads')}")
    print(f"  files          {report['file_count']:,}")
    print(f"  total size     {format_bytes(report['total_bytes'])}")

    print(f"\n  File types\n  {'-' * 44}")
    for row in report["extensions"][:12]:
        print(f"  {row['extension']:<12} {row['count']:>6} files  {format_bytes(row['bytes']):>12}")

    print(f"\n  Top-level layout\n  {'-' * 44}")
    for row in report["top_level"][:25]:
        print(f"  {row['entry']:<24} {row['count']:>5} files  {format_bytes(row['bytes']):>12}")

    print(f"\n  Target languages\n  {'-' * 62}")
    print(f"  {'code':<6} {'name':<12} {'files':>6}  {'size':>12}  example")
    selected = 0
    for code, info in report["languages"].items():
        selected += info["bytes"]
        example = info["files"][0] if info["files"] else "(no match)"
        print(
            f"  {code:<6} {info['name']:<12} {info['file_count']:>6}  "
            f"{format_bytes(info['bytes']):>12}  {example}"
        )
    share = (selected / report["total_bytes"] * 100) if report["total_bytes"] else 0.0
    print(f"\n  Selected: {format_bytes(selected)} of {format_bytes(report['total_bytes'])}"
          f" ({share:.1f}% of the repository)")

    if list_files and report.get("all_files"):
        print(f"\n  Complete file listing\n  {'-' * 62}")
        for row in report["all_files"]:
            print(f"  {format_bytes(row['bytes']):>12}  {row['path']}")
    print()


# --------------------------------------------------------------------------
# local inspection
# --------------------------------------------------------------------------


def inspect_local(root: Path, samples: int) -> dict[str, Any]:
    if not root.exists():
        return {"mode": "local", "root": str(root), "exists": False, "files": []}

    entries: list[dict[str, Any]] = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        entries.append(_describe_file(path, root, samples))

    return {
        "mode": "local",
        "root": str(root),
        "exists": True,
        "file_count": len(entries),
        "total_bytes": sum(entry["bytes"] for entry in entries),
        "files": entries,
    }


def _describe_file(path: Path, root: Path, samples: int) -> dict[str, Any]:
    info: dict[str, Any] = {
        "path": path.relative_to(root).as_posix(),
        "bytes": path.stat().st_size,
        "suffix": path.suffix.lower(),
        "records": None,
        "columns": None,
        "samples": [],
        "note": None,
    }

    try:
        if path.suffix.lower() == ".zip":
            info.update(_describe_zip(path, samples))
        elif path.suffix.lower() == ".parquet":
            info.update(_describe_parquet(path, samples))
        elif path.suffix.lower() in _TEXT_SUFFIXES:
            with path.open("rb") as handle:
                info.update(_describe_stream(handle, path.name, path.stat().st_size, samples))
        else:
            info["note"] = "binary or unrecognised format -- size only"
    except Exception as exc:  # noqa: BLE001 - a bad file must not abort the sweep
        info["note"] = f"could not read: {type(exc).__name__}: {exc}"

    return info


def _describe_zip(path: Path, samples: int) -> dict[str, Any]:
    """Peek inside an archive without extracting a single byte to disk."""
    with zipfile.ZipFile(path) as bundle:
        members = [m for m in bundle.infolist() if not m.is_dir()]
        detail: dict[str, Any] = {
            "note": f"zip archive, {len(members)} member(s) (not extracted)",
            "members": [
                {"name": m.filename, "bytes": m.file_size} for m in sorted(
                    members, key=lambda m: m.filename
                )[:20]
            ],
        }
        candidates = [m for m in members if Path(m.filename).suffix.lower() in _TEXT_SUFFIXES]
        if candidates and samples > 0:
            first = min(candidates, key=lambda m: m.filename)
            with bundle.open(first) as handle:
                inner = _describe_stream(handle, first.filename, first.file_size, samples)
            detail["columns"] = inner.get("columns")
            detail["samples"] = inner.get("samples", [])
            detail["sampled_member"] = first.filename
        return detail


def _describe_parquet(path: Path, samples: int) -> dict[str, Any]:
    try:
        import pyarrow.parquet as pq
    except ImportError:
        return {"note": "parquet file -- install pyarrow to inspect it"}

    parquet = pq.ParquetFile(path)
    head = next(parquet.iter_batches(batch_size=max(samples, 1)), None)
    rows = head.to_pylist()[:samples] if head is not None else []
    return {
        "records": parquet.metadata.num_rows,
        "columns": [field.name for field in parquet.schema_arrow],
        "samples": rows,
    }


def _describe_stream(handle: Any, name: str, size: int, samples: int) -> dict[str, Any]:
    """Infer the record layout of a text stream (JSONL, JSON array, CSV/TSV).

    *handle* is a binary stream, possibly non-seekable (a zip member), so
    everything here is done in a single forward pass.
    """
    text = io.TextIOWrapper(handle, encoding="utf-8", errors="replace", newline="")
    suffix = Path(name).suffix.lower()

    if suffix in {".csv", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else ","
        reader = csv.DictReader(text, delimiter=delimiter)
        rows: list[Any] = []
        count = 0
        for row in reader:
            count += 1
            if len(rows) < samples:
                rows.append(dict(row))
        return {
            "records": count,
            "columns": list(reader.fieldnames or []),
            "samples": rows,
            "note": f"delimited text (delimiter={delimiter!r})",
        }

    first = text.readline()
    stripped = first.lstrip()

    # A single JSON array rather than JSON Lines. Only safe to parse whole.
    if stripped.startswith("["):
        if size > _MAX_SCAN_BYTES:
            return {"note": f"JSON array, {format_bytes(size)} -- too large to sample cheaply"}
        try:
            payload = json.loads(first + text.read())
        except json.JSONDecodeError as exc:
            return {"note": f"looks like a JSON array but did not parse: {exc}"}
        items = payload if isinstance(payload, list) else [payload]
        return {
            "records": len(items),
            "columns": _infer_columns(items[:samples] or items[:1]),
            "samples": items[:samples],
            "note": "JSON array",
        }

    if not stripped:
        return {"records": 0, "note": "empty file"}

    try:
        rows = [json.loads(stripped)]
    except json.JSONDecodeError:
        return {"note": "plain text -- no structured records detected"}

    count = 1
    for line in text:
        if not line.strip():
            continue
        count += 1
        if len(rows) < samples:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    return {
        "records": count,
        "columns": _infer_columns(rows),
        "samples": rows[:samples],
        "note": "JSON Lines",
    }


def _infer_columns(rows: Sequence[Any]) -> list[str]:
    keys: dict[str, None] = {}
    for row in rows:
        if isinstance(row, dict):
            for key in row:
                keys.setdefault(str(key), None)
    return list(keys)


def print_local(report: dict[str, Any], samples: int) -> None:
    print(f"\n{'=' * 78}")
    print(f"LOCAL  {report['root']}")
    print(f"{'=' * 78}")

    if not report["exists"]:
        print("  Directory does not exist yet -- nothing downloaded.\n"
              "  Run: python scripts/download_datasets.py --plan-only\n")
        return
    if not report["files"]:
        print("  Directory is empty -- nothing downloaded yet.\n")
        return

    print(f"  {report['file_count']} file(s), {format_bytes(report['total_bytes'])} total\n")

    for entry in report["files"]:
        print(f"  {entry['path']}")
        detail = [format_bytes(entry["bytes"])]
        if entry.get("records") is not None:
            detail.append(f"{entry['records']:,} records")
        if entry.get("note"):
            detail.append(str(entry["note"]))
        print(f"      {'  |  '.join(detail)}")

        if entry.get("columns"):
            print(f"      columns: {', '.join(entry['columns'])}")
        for member in (entry.get("members") or [])[:5]:
            print(f"      member: {member['name']}  ({format_bytes(member['bytes'])})")
        for row in (entry.get("samples") or [])[:samples]:
            rendered = json.dumps(row, ensure_ascii=False)
            print(f"      sample: {rendered[:160]}{'...' if len(rendered) > 160 else ''}")
        print()


# --------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)
    source_name = args.source or config.default_source

    # Default: inspect whatever is available without being told.
    do_remote, do_local = args.remote, args.local
    if not do_remote and not do_local:
        raw_dir = config.resolve(args.path or config.source(source_name)["raw_dir"])
        do_local = raw_dir.exists() and any(raw_dir.rglob("*"))
        do_remote = not do_local

    reports: list[dict[str, Any]] = []

    if do_remote:
        try:
            report = inspect_remote(config, source_name, args)
        except HubError as exc:
            logger.error("%s", exc)
            return 1
        reports.append(report)
        if not args.json:
            print_remote(report, config, args.list_files)

    if do_local:
        root = config.resolve(args.path or config.source(source_name)["raw_dir"])
        report = inspect_local(root, args.samples)
        reports.append(report)
        if not args.json:
            print_local(report, args.samples)

    if args.json:
        json.dump(reports if len(reports) > 1 else reports[0], sys.stdout,
                  indent=2, ensure_ascii=False, default=str)
        sys.stdout.write("\n")

    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
