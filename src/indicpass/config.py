"""Loading and access for the YAML configuration in ``config/``.

Nothing in this project hardcodes a path. Scripts ask :class:`Config` for a
named path key and get back an absolute :class:`~pathlib.Path` anchored to the
project root, which is discovered at import time. That is what lets the same
checkout run unchanged on the development PC and on the training PC.
"""

from __future__ import annotations

import os
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

__all__ = [
    "Config",
    "ConfigError",
    "Language",
    "find_project_root",
    "load_config",
]

# A directory is the project root when it contains all of these.
_ROOT_MARKERS: tuple[str, ...] = ("pyproject.toml", "config/project.yaml")

_CONFIG_FILES: dict[str, str] = {
    "project": "project.yaml",
    "languages": "languages.yaml",
    "dataset": "dataset.yaml",
    "password": "password.yaml",
}


class ConfigError(RuntimeError):
    """Raised when configuration is missing, unreadable or malformed."""


def find_project_root(start: Path | None = None) -> Path:
    """Return the project root directory.

    Honours ``INDICPASS_ROOT`` if set, otherwise walks up from *start*
    (defaulting to this file) looking for the marker files.
    """
    env_root = os.environ.get("INDICPASS_ROOT")
    if env_root:
        root = Path(env_root).expanduser().resolve()
        if not root.is_dir():
            raise ConfigError(f"INDICPASS_ROOT points at a missing directory: {root}")
        return root

    origin = (start or Path(__file__)).resolve()
    for candidate in (origin, *origin.parents):
        if candidate.is_dir() and all((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate

    raise ConfigError(
        f"Could not locate the IndicPass project root above {origin}.\n"
        f"Expected a directory containing: {', '.join(_ROOT_MARKERS)}.\n"
        "Run scripts from the project root, or set INDICPASS_ROOT."
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ConfigError(
            f"Missing configuration file: {path}\n"
            "The config/ directory ships with the repository -- restore it from git."
        )
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:  # pragma: no cover - depends on user edits
        raise ConfigError(f"{path} is not valid YAML: {exc}") from exc

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path} must contain a YAML mapping at the top level.")
    return data


def _parse_codepoint_range(spec: str) -> tuple[int, int]:
    """Parse an inclusive hex range such as ``"0900-097F"`` or a single ``"200D"``."""
    text = str(spec).strip()
    try:
        if "-" in text:
            low, high = (part.strip() for part in text.split("-", 1))
            start, end = int(low, 16), int(high, 16)
        else:
            start = end = int(text, 16)
    except ValueError as exc:
        raise ConfigError(f"Bad Unicode range {spec!r}; expected hex like '0900-097F'.") from exc

    if start > end:
        raise ConfigError(f"Unicode range {spec!r} starts above where it ends.")
    return start, end


@dataclass(frozen=True)
class Language:
    """One target language, as declared in ``config/languages.yaml``."""

    code: str  # ISO 639-3 -- the canonical key used throughout the project
    name: str
    native_name: str
    iso_639_1: str
    romanized_label: str
    script: str
    script_code: str
    unicode_ranges: tuple[tuple[int, int], ...]
    dataset_codes: Mapping[str, str]

    def dataset_code(self, source: str) -> str:
        """Identifier this language goes by in *source*; falls back to the ISO code."""
        return self.dataset_codes.get(source, self.code)

    def in_script(self, char: str) -> bool:
        """True when *char* falls inside this language's script blocks."""
        point = ord(char)
        return any(start <= point <= end for start, end in self.unicode_ranges)

    def __str__(self) -> str:  # pragma: no cover - display only
        return f"{self.code} ({self.name})"


class Config:
    """Parsed view over the three YAML files in ``config/``."""

    def __init__(
        self,
        root: Path,
        project: dict[str, Any],
        languages: dict[str, Any],
        dataset: dict[str, Any],
        password: dict[str, Any] | None = None,
    ) -> None:
        self.root = root
        self.project = project
        self.dataset = dataset
        self.password = dict(password or {})
        self._languages_raw = languages
        self._languages = _build_languages(languages)
        self._alias_index = _build_alias_index(self._languages, languages.get("aliases") or {})

    # -- metadata ----------------------------------------------------------

    @property
    def name(self) -> str:
        return str(self.project.get("project", {}).get("name", "IndicPass"))

    @property
    def version(self) -> str:
        return str(self.project.get("project", {}).get("version", "0.0.0"))

    @property
    def seed(self) -> int:
        return int(self.project.get("project", {}).get("seed", 42))

    # -- paths -------------------------------------------------------------

    def path(self, key: str, *parts: str) -> Path:
        """Resolve a named path from ``project.yaml``'s ``paths`` section."""
        paths = self.project.get("paths", {})
        if key not in paths:
            known = ", ".join(sorted(paths)) or "<none>"
            raise ConfigError(f"Unknown path key {key!r}. Known keys: {known}")

        relative = Path(str(paths[key]))
        if relative.is_absolute():
            raise ConfigError(
                f"paths.{key} in config/project.yaml is absolute ({relative}). "
                "Only relative paths are allowed so the repo stays portable."
            )
        return self.root.joinpath(relative, *parts)

    def resolve(self, relative: str | Path) -> Path:
        """Anchor any relative path string from config to the project root."""
        candidate = Path(str(relative))
        return candidate if candidate.is_absolute() else self.root / candidate

    def ensure_dir(self, key: str, *parts: str) -> Path:
        """Like :meth:`path`, but creates the directory if it does not exist."""
        target = self.path(key, *parts)
        target.mkdir(parents=True, exist_ok=True)
        return target

    def relative(self, path: Path) -> str:
        """Render *path* relative to the root, always in POSIX form.

        Forward slashes are not cosmetic here. This string is what lands in the
        download and preprocess manifests, which are committed and read back on
        the other machine; a Windows-separated ``data\\raw\\aksharantar`` is a
        single weirdly-named file on Linux, not a path.
        """
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return Path(path).as_posix()

    # -- languages ---------------------------------------------------------

    @property
    def languages(self) -> dict[str, Language]:
        return dict(self._languages)

    @property
    def default_language_codes(self) -> list[str]:
        codes = self._languages_raw.get("default_targets") or list(self._languages)
        return [str(code) for code in codes]

    def language(self, code: str) -> Language:
        """Look up a language by ISO 639-3/639-1 code, name or alias."""
        key = self._alias_index.get(str(code).strip().casefold())
        if key is None:
            known = ", ".join(sorted(self._languages))
            raise ConfigError(f"Unknown language {code!r}. Configured languages: {known}")
        return self._languages[key]

    def resolve_languages(self, codes: Sequence[str] | None) -> list[Language]:
        """Normalise a CLI ``--languages`` list, defaulting to the configured targets.

        Duplicates are collapsed and the original ordering is preserved.
        """
        wanted = list(codes) if codes else self.default_language_codes
        seen: set[str] = set()
        resolved: list[Language] = []
        for item in wanted:
            language = self.language(item)
            if language.code not in seen:
                seen.add(language.code)
                resolved.append(language)
        return resolved

    @property
    def neutral_codepoints(self) -> frozenset[int]:
        """Codepoints allowed in native text regardless of script."""
        specs: Iterable[str] = self._languages_raw.get("neutral_codepoints") or []
        points: set[int] = set()
        for spec in specs:
            start, end = _parse_codepoint_range(str(spec))
            points.update(range(start, end + 1))
        return frozenset(points)

    @property
    def neutral_categories(self) -> frozenset[str]:
        """Unicode general categories that never count against a script check."""
        return frozenset(str(c) for c in (self._languages_raw.get("neutral_categories") or []))

    def is_neutral(self, char: str) -> bool:
        """True when *char* is script-neutral (joiner, digit, punctuation, space)."""
        return ord(char) in self.neutral_codepoints or (
            unicodedata.category(char) in self.neutral_categories
        )

    # -- dataset sources ---------------------------------------------------

    @property
    def default_source(self) -> str:
        return str(self.dataset.get("default_source", "aksharantar"))

    @property
    def source_names(self) -> list[str]:
        return sorted(self.dataset.get("sources", {}))

    def source(self, name: str | None = None) -> dict[str, Any]:
        """Return the config block for a dataset source."""
        key = name or self.default_source
        sources = self.dataset.get("sources", {})
        if key not in sources:
            known = ", ".join(sorted(sources)) or "<none>"
            raise ConfigError(f"Unknown dataset source {key!r}. Configured sources: {known}")
        return dict(sources[key])

    @property
    def splits(self) -> dict[str, Any]:
        return dict(self.dataset.get("splits", {}))

    @property
    def split_names(self) -> list[str]:
        return [str(n) for n in self.splits.get("names", ["train", "validation", "test"])]

    @property
    def preprocessing(self) -> dict[str, Any]:
        return dict(self.dataset.get("preprocessing", {}))

    @property
    def validation(self) -> dict[str, Any]:
        return dict(self.dataset.get("validation", {}))

    # -- password engine ---------------------------------------------------

    def password_section(self, key: str) -> dict[str, Any]:
        """Return one top-level block of ``config/password.yaml``.

        Raises rather than returning ``{}`` for a missing block: the guess
        model has no safe default costs, and silently scoring passwords with a
        half-empty configuration would produce numbers that look real.
        """
        if key not in self.password:
            known = ", ".join(sorted(self.password)) or "<none>"
            raise ConfigError(
                f"config/password.yaml has no {key!r} section. Present: {known}"
            )
        block = self.password[key]
        if not isinstance(block, dict):
            raise ConfigError(f"password.{key} must be a mapping, got {type(block).__name__}.")
        return dict(block)

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"<Config {self.name} v{self.version} root={self.root}>"


def _build_languages(raw: dict[str, Any]) -> dict[str, Language]:
    entries = raw.get("languages") or {}
    if not entries:
        raise ConfigError("config/languages.yaml declares no languages.")

    languages: dict[str, Language] = {}
    for code, spec in entries.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"languages.{code} must be a mapping.")
        ranges = tuple(_parse_codepoint_range(r) for r in spec.get("unicode_ranges") or [])
        if not ranges:
            raise ConfigError(f"languages.{code} declares no unicode_ranges.")

        languages[str(code)] = Language(
            code=str(code),
            name=str(spec.get("name", code)),
            native_name=str(spec.get("native_name", "")),
            iso_639_1=str(spec.get("iso_639_1", "")),
            romanized_label=str(spec.get("romanized_label", "")),
            script=str(spec.get("script", "")),
            script_code=str(spec.get("script_code", "")),
            unicode_ranges=ranges,
            dataset_codes=dict(spec.get("dataset_codes") or {}),
        )
    return languages


def _build_alias_index(
    languages: Mapping[str, Language],
    aliases: Mapping[str, Sequence[str]],
) -> dict[str, str]:
    """Map every accepted spelling (case-folded) to a canonical ISO 639-3 code."""
    index: dict[str, str] = {}

    def register(token: str, code: str) -> None:
        key = token.strip().casefold()
        if key:
            index.setdefault(key, code)

    for code, language in languages.items():
        register(code, code)
        register(language.iso_639_1, code)
        register(language.name, code)
        register(language.romanized_label, code)
        register(language.script, code)
        for alias in aliases.get(code, ()):  # type: ignore[arg-type]
            register(str(alias), code)
    return index


@lru_cache(maxsize=4)
def _load_cached(root: Path) -> Config:
    config_dir = root / "config"
    loaded = {name: _read_yaml(config_dir / filename) for name, filename in _CONFIG_FILES.items()}
    return Config(
        root=root,
        project=loaded["project"],
        languages=loaded["languages"],
        dataset=loaded["dataset"],
        password=loaded["password"],
    )


def load_config(root: Path | None = None) -> Config:
    """Load (and memoise) the project configuration.

    Parameters
    ----------
    root:
        Project root. Auto-detected when omitted.
    """
    return _load_cached(root.resolve() if root else find_project_root())
