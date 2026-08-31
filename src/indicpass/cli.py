"""Shared command-line plumbing for the scripts in ``scripts/``.

Keeps the four dataset CLIs consistent: same flag names, same startup banner,
same confirmation behaviour, same error formatting.
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import suppress
from typing import Sequence

from indicpass.config import Config, ConfigError, load_config
from indicpass.logging_utils import get_logger, setup_logging

__all__ = ["add_common_arguments", "confirm", "load_env", "run_cli", "startup"]


def load_env(root) -> None:
    """Load ``.env`` from the project root into the environment, if present.

    ``.env.example`` tells the user to put ``HF_TOKEN`` here, so something has
    to actually read it. Existing environment variables win, and a missing
    ``python-dotenv`` is not fatal -- the file is optional in the first place.
    """
    env_file = root / ".env"
    if not env_file.is_file():
        return
    try:
        from dotenv import load_dotenv
    except ImportError:  # pragma: no cover - depends on the install
        return
    load_dotenv(env_file, override=False)


def add_common_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """Attach the flags every IndicPass script understands."""
    parser.add_argument(
        "--languages",
        "-l",
        nargs="+",
        metavar="LANG",
        help=(
            "Languages to process, as ISO 639-3 codes, ISO 639-1 codes or names "
            "(e.g. hin ta telugu). Defaults to config/languages.yaml default_targets."
        ),
    )
    parser.add_argument(
        "--source",
        "-s",
        metavar="NAME",
        help="Dataset source from config/dataset.yaml. Defaults to default_source.",
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Console verbosity. Overrides config/project.yaml.",
    )
    parser.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="Answer yes to confirmation prompts. Required for non-interactive runs.",
    )
    return parser


def startup(args: argparse.Namespace, script_name: str) -> tuple[Config, logging.Logger]:
    """Load config, configure logging and log a one-line banner."""
    config = load_config()
    load_env(config.root)
    setup_logging(config, level=getattr(args, "log_level", None))
    logger = get_logger(script_name)
    logger.debug("%s v%s | root=%s", config.name, config.version, config.root)
    return config, logger


def confirm(question: str, *, assume_yes: bool = False) -> bool:
    """Ask a yes/no question on the terminal.

    Returns ``False`` rather than blocking when stdin is not a TTY, so a
    forgotten ``--yes`` in a scheduled job fails safe instead of hanging.
    """
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        print(f"{question} [y/N] -> no TTY available; pass --yes to proceed.", file=sys.stderr)
        return False

    try:
        answer = input(f"{question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in {"y", "yes"}


def force_utf8_output() -> None:
    """Make stdout and stderr carry Indic text regardless of the platform.

    Every script here can print Devanagari. On Windows, Python writes to a
    console using UTF-8 but falls back to the locale encoding -- cp1252 on a
    default install -- the moment stdout is a pipe or a file. So the tool works
    when a human watches it and dies with UnicodeEncodeError under
    ``> out.txt``, ``| more``, or CI. Reconfiguring here fixes every script at
    once, because they all enter through run_cli.

    Guarded: a caller may have replaced these streams with something that has
    no reconfigure (pytest's capture objects, for one), and failing to set an
    encoding is never worth aborting the run over.
    """
    for stream in (sys.stdout, sys.stderr):
        with suppress(AttributeError, ValueError, OSError):
            stream.reconfigure(encoding="utf-8")


def run_cli(main, argv: Sequence[str] | None = None) -> int:
    """Invoke *main* with uniform handling of config errors and Ctrl-C."""
    force_utf8_output()
    try:
        return int(main(argv) or 0)
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 130
