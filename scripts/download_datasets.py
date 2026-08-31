#!/usr/bin/env python
"""Download raw datasets from the Hugging Face Hub into ``data/raw/``.

Selective by design. Aksharantar is ~26M pairs across 21 languages; IndicPass
needs five of them. This script resolves the exact remote files for the
requested languages, prints their combined size, and refuses to transfer
anything until that plan is confirmed -- so a mistyped command cannot pull tens
of gigabytes.

Raw data is written once and then treated as immutable: preprocessing reads it
and writes elsewhere. A ``download_manifest.json`` recording the repository
revision and every file's size is written alongside it so the same raw corpus
can be reproduced byte-for-byte on the training PC.

Examples
--------
    python scripts/download_datasets.py --list-languages
    python scripts/download_datasets.py --plan-only
    python scripts/download_datasets.py --languages hin tam
    python scripts/download_datasets.py --languages hin --yes --no-extract
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

import _bootstrap  # noqa: F401  -- puts src/ on sys.path

from indicpass.cli import add_common_arguments, confirm, run_cli, startup
from indicpass.config import Config, Language
from indicpass.hub import (
    HubError,
    RemoteFile,
    download_files,
    extract_archives,
    list_remote_files,
    match_files,
    repo_metadata,
    write_manifest,
)
from indicpass.logging_utils import format_bytes

SCRIPT = "download_datasets"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="download_datasets.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_common_arguments(parser)
    parser.add_argument(
        "--list-languages",
        action="store_true",
        help="Print the configured target languages and exit. No network access.",
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Resolve and print the download plan, then stop without downloading.",
    )
    parser.add_argument(
        "--revision",
        metavar="SHA",
        help="Pin a specific repository revision. Defaults to the current main.",
    )
    parser.add_argument(
        "--pattern",
        nargs="+",
        metavar="GLOB",
        help=(
            "Override the source's match_patterns. Use {code} as the language "
            "placeholder, e.g. --pattern '{code}.zip'."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        metavar="DIR",
        help="Override the source's raw_dir. Relative paths resolve from the project root.",
    )
    parser.add_argument(
        "--no-extract",
        action="store_true",
        help="Leave downloaded archives packed instead of extracting them.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-extract archives that have already been unpacked.",
    )
    parser.add_argument(
        "--max-bytes",
        type=float,
        default=25.0,
        metavar="GIB",
        help="Abort if the plan exceeds this many GiB (default: 25). A safety rail.",
    )
    return parser


def _print_languages(config: Config) -> None:
    print(f"\nConfigured target languages ({config.name} v{config.version})\n")
    header = f"  {'code':<6} {'639-1':<6} {'language':<12} {'romanized':<12} {'script':<12} native"
    print(header)
    print("  " + "-" * (len(header) - 2))
    for language in config.resolve_languages(None):
        print(
            f"  {language.code:<6} {language.iso_639_1:<6} {language.name:<12} "
            f"{language.romanized_label:<12} {language.script:<12} {language.native_name}"
        )
    print("\n  Pass any of these spellings to --languages.\n")


def _resolve_plan(
    files: Sequence[RemoteFile],
    languages: Sequence[Language],
    patterns: Sequence[str],
    source_name: str,
) -> dict[str, list[RemoteFile]]:
    return {
        language.code: match_files(files, patterns, language.dataset_code(source_name))
        for language in languages
    }


def _print_plan(
    plan: dict[str, list[RemoteFile]],
    languages: Sequence[Language],
    metadata: dict[str, object],
    destination: Path,
    config: Config,
) -> int:
    by_code = {language.code: language for language in languages}
    total = 0

    print(f"\nDownload plan -- {metadata['repo_id']} @ {str(metadata['revision'])[:12]}")
    print(f"Destination:   {config.relative(destination)}\n")
    print(f"  {'language':<18} {'files':>6}  {'size':>12}  matched")
    print("  " + "-" * 76)

    for code, matches in plan.items():
        size = sum(entry.size_or_zero for entry in matches)
        total += size
        sample = ", ".join(entry.path for entry in matches[:2])
        if len(matches) > 2:
            sample += f", +{len(matches) - 2} more"
        label = f"{code} ({by_code[code].name})"
        print(
            f"  {label:<18} {len(matches):>6}  {format_bytes(size):>12}  "
            f"{sample or '(no match)'}"
        )

    print("  " + "-" * 76)
    file_count = sum(len(matches) for matches in plan.values())
    print(f"  {'TOTAL':<18} {file_count:>6}  {format_bytes(total):>12}\n")
    return total


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    config, logger = startup(args, SCRIPT)

    if args.list_languages:
        _print_languages(config)
        return 0

    source_name = args.source or config.default_source
    source = config.source(source_name)

    if not source.get("enabled", False):
        logger.error(
            "Source %r is disabled in config/dataset.yaml. Set enabled: true to use it.",
            source_name,
        )
        return 1
    if source.get("type") != "huggingface":
        logger.error(
            "Source %r has type %r; this script only handles 'huggingface' sources.",
            source_name,
            source.get("type"),
        )
        return 1

    repo_id = str(source["repo_id"])
    repo_type = str(source.get("repo_type", "dataset"))
    patterns = args.pattern or source.get("match_patterns") or ["*{code}*"]
    languages = config.resolve_languages(args.languages)
    destination = (
        config.resolve(args.output_dir) if args.output_dir else config.resolve(source["raw_dir"])
    )

    logger.info(
        "Resolving %s for %s (metadata only, no data transferred)",
        repo_id,
        ", ".join(language.code for language in languages),
    )

    try:
        metadata = repo_metadata(repo_id, repo_type=repo_type, revision=args.revision)
        files = list_remote_files(
            repo_id, repo_type=repo_type, revision=metadata.get("revision") or args.revision
        )
    except HubError as exc:
        logger.error("%s", exc)
        return 1

    logger.info("Repository holds %d files at revision %s", len(files), metadata["revision"])
    if metadata.get("gated"):
        logger.warning("This dataset is gated -- accept its terms on the Hub and set HF_TOKEN.")

    plan = _resolve_plan(files, languages, patterns, source_name)
    total_bytes = _print_plan(plan, languages, metadata, destination, config)

    missing = [code for code, matches in plan.items() if not matches]
    if missing:
        logger.error(
            "No files matched for: %s. The repository layout differs from "
            "config/dataset.yaml match_patterns. Inspect the real listing with:\n"
            "    python scripts/inspect_dataset.py --remote --list-files",
            ", ".join(missing),
        )
        return 1

    limit = int(args.max_bytes * 1024**3)
    if total_bytes > limit:
        logger.error(
            "Plan is %s, above the --max-bytes rail of %.1f GiB. Narrow --languages "
            "or --pattern, or raise --max-bytes deliberately.",
            format_bytes(total_bytes),
            args.max_bytes,
        )
        return 1

    if args.plan_only:
        logger.info("--plan-only: stopping before any download.")
        return 0

    if not confirm(f"Download {format_bytes(total_bytes)} to {config.relative(destination)}?",
                   assume_yes=args.yes):
        logger.info("Aborted. Nothing downloaded.")
        return 0

    wanted = sorted({entry.path for matches in plan.values() for entry in matches})
    logger.info("Downloading %d files...", len(wanted))
    try:
        download_files(
            repo_id,
            wanted,
            destination,
            repo_type=repo_type,
            revision=metadata.get("revision") or args.revision,
        )
    except HubError as exc:
        logger.error("%s", exc)
        return 1

    extracted: list[Path] = []
    if source.get("extract_archives", True) and not args.no_extract:
        archives = [destination / path for path in wanted if path.lower().endswith(".zip")]
        present = [archive for archive in archives if archive.is_file()]
        if present:
            logger.info("Extracting %d archive(s)...", len(present))
            extracted = extract_archives(present, destination / "extracted", force=args.force)

    manifest = write_manifest(
        destination / "download_manifest.json",
        {
            "source": source_name,
            "repo_id": repo_id,
            "repo_type": repo_type,
            "revision": metadata.get("revision"),
            "languages": [language.code for language in languages],
            "match_patterns": list(patterns),
            "total_bytes": total_bytes,
            "files": [
                {"path": entry.path, "bytes": entry.size_or_zero}
                for matches in plan.values()
                for entry in matches
            ],
            "extracted_to": [config.relative(path) for path in extracted],
        },
    )

    logger.info("Raw data ready in %s", config.relative(destination))
    logger.info("Manifest written to %s", config.relative(manifest))
    logger.info("Next: python scripts/inspect_dataset.py --local")
    return 0


if __name__ == "__main__":
    sys.exit(run_cli(main))
