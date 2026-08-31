"""Console and file logging shared by every IndicPass script.

Uses ``rich`` for readable console output when it is installed and degrades to
plain ``logging`` when it is not, so the pipeline still runs in a bare
environment. File logging is rotated and written to the path configured in
``config/project.yaml``.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence, TypeVar

__all__ = ["format_bytes", "get_logger", "progress", "setup_logging"]

T = TypeVar("T")

_ROOT_LOGGER_NAME = "indicpass"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a namespaced logger. Call :func:`setup_logging` once first."""
    if not name or name == _ROOT_LOGGER_NAME:
        return logging.getLogger(_ROOT_LOGGER_NAME)
    # Turn "__main__" / "scripts/foo.py" into something readable in the log.
    leaf = Path(name).stem if name.endswith(".py") else name
    return logging.getLogger(f"{_ROOT_LOGGER_NAME}.{leaf}")


def setup_logging(
    config: Any | None = None,
    *,
    level: str | int | None = None,
    log_to_file: bool = True,
) -> logging.Logger:
    """Configure the ``indicpass`` logger tree. Safe to call more than once.

    Precedence for the level: explicit *level* argument, then the
    ``INDICPASS_LOG_LEVEL`` environment variable, then ``config/project.yaml``.
    """
    settings: dict[str, Any] = {}
    root_dir: Path | None = None
    if config is not None:
        settings = dict(getattr(config, "project", {}).get("logging", {}))
        root_dir = getattr(config, "root", None)

    resolved = level or os.environ.get("INDICPASS_LOG_LEVEL") or settings.get("level", "INFO")
    numeric = logging.getLevelName(str(resolved).upper()) if isinstance(resolved, str) else resolved
    if not isinstance(numeric, int):
        numeric = logging.INFO

    logger = logging.getLogger(_ROOT_LOGGER_NAME)
    logger.setLevel(numeric)
    # Own our handlers completely; re-running must not duplicate output.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    logger.propagate = False

    logger.addHandler(_console_handler(numeric, settings))

    log_file = settings.get("file")
    if log_to_file and log_file and root_dir is not None:
        handler = _file_handler(Path(root_dir) / str(log_file), settings)
        if handler is not None:
            logger.addHandler(handler)

    return logger


def _console_handler(level: int, settings: dict[str, Any]) -> logging.Handler:
    try:
        from rich.logging import RichHandler
    except ImportError:
        handler: logging.Handler = logging.StreamHandler(stream=sys.stderr)
        handler.setFormatter(
            logging.Formatter(
                str(settings.get("format", "%(asctime)s | %(levelname)-8s | %(message)s")),
                datefmt=str(settings.get("date_format", "%Y-%m-%d %H:%M:%S")),
            )
        )
    else:
        handler = RichHandler(
            rich_tracebacks=True,
            show_path=False,
            omit_repeated_times=False,
            log_time_format="[%H:%M:%S]",
        )
        handler.setFormatter(logging.Formatter("%(message)s"))

    handler.setLevel(level)
    return handler


def _file_handler(path: Path, settings: dict[str, Any]) -> logging.Handler | None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            path,
            maxBytes=int(settings.get("max_bytes", 5 * 1024 * 1024)),
            backupCount=int(settings.get("backup_count", 3)),
            encoding="utf-8",
        )
    except OSError as exc:
        # A read-only or missing results/ directory must not kill the run.
        logging.getLogger(_ROOT_LOGGER_NAME).warning("File logging disabled (%s): %s", path, exc)
        return None

    handler.setFormatter(
        logging.Formatter(
            str(settings.get("format", "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")),
            datefmt=str(settings.get("date_format", "%Y-%m-%d %H:%M:%S")),
        )
    )
    handler.setLevel(logging.DEBUG)
    return handler


def progress(
    iterable: Iterable[T],
    description: str = "",
    *,
    total: int | None = None,
    enabled: bool = True,
) -> Iterator[T]:
    """Wrap *iterable* in a tqdm progress bar, or pass it straight through.

    Falls back silently when tqdm is missing or when output is not a terminal,
    which keeps captured logs clean.
    """
    if not enabled or not sys.stderr.isatty():
        return iter(iterable)
    try:
        from tqdm import tqdm
    except ImportError:
        return iter(iterable)
    return iter(tqdm(iterable, desc=description, total=total, unit="rec", leave=False))


def format_bytes(size: float) -> str:
    """Human-readable byte count, e.g. ``1.4 GiB``."""
    units: Sequence[str] = ("B", "KiB", "MiB", "GiB", "TiB")
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:,.1f} {unit}" if unit != "B" else f"{value:,.0f} B"
        value /= 1024
    return f"{value:,.1f} {units[-1]}"  # pragma: no cover - unreachable
