"""Generic password-strength estimators to compare IndicPass against.

The research question is whether explicit Romanized-Indic lexical modelling
tells you something a generic estimator misses. That question is meaningless
without the generic estimator, so it lives here behind a small interface:
:class:`PasswordStrengthBaseline` produces a guess count and a 0-4 score for a
password, and the benchmark treats every implementation identically.

The interface exists so that zxcvbn's internals stay in this file. zxcvbn
returns a rich result -- ranked dictionary hits, l33t maps, spatial patterns --
and every field of it is shaped by zxcvbn's own model. Letting that shape reach
the meter or the report would make the comparison a comparison of data
structures. What crosses the boundary is a :class:`BaselineEstimate`: guesses,
a score, pattern *names*, and feedback text.

Nothing leaves here holding password content
--------------------------------------------
zxcvbn's result echoes the password back, and each entry of its ``sequence``
carries the matched substring and, for a dictionary hit, the wordlist entry it
matched. Those are pieces of the password. :class:`ZxcvbnBaseline` keeps the
pattern names and drops the rest, so a benchmark row can say "zxcvbn read this
as dictionary + date" without the file recording what the date was.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "BaselineEstimate",
    "BaselineUnavailable",
    "PasswordStrengthBaseline",
    "ZxcvbnBaseline",
    "load_baseline",
]


class BaselineUnavailable(RuntimeError):
    """Raised when a configured baseline cannot be constructed."""


@dataclass(frozen=True)
class BaselineEstimate:
    """One baseline's verdict on one password.

    ``log10_guesses`` is stored rather than derived so that a baseline whose
    guess count overflows a float still reports a usable number, matching the
    convention in :mod:`indicpass.password.result`.
    """

    guesses: float
    log10_guesses: float
    score: int
    #: Pattern names only -- never the substrings they matched.
    patterns: tuple[str, ...] = ()
    #: Human-readable advice, when the implementation offers any.
    feedback: tuple[str, ...] = ()
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "guesses": self.guesses,
            "log10_guesses": round(self.log10_guesses, 6),
            "score": self.score,
            "patterns": list(self.patterns),
            "feedback": list(self.feedback),
            **self.extra,
        }


class PasswordStrengthBaseline(ABC):
    """A generic password-strength estimator IndicPass can be measured against."""

    #: Short identifier used as the result-schema key, e.g. ``"zxcvbn"``.
    name: str = "baseline"
    #: Version of the underlying implementation, for the report header.
    version: str = "unknown"

    @abstractmethod
    def estimate(self, password: str) -> BaselineEstimate:
        """Score *password*. Must not retain or return the password itself."""

    def describe(self) -> dict[str, Any]:
        """Provenance for a report header."""
        return {"name": self.name, "version": self.version}

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"<{type(self).__name__} {self.name} {self.version}>"


class ZxcvbnBaseline(PasswordStrengthBaseline):
    """Dropbox's zxcvbn, via the maintained ``zxcvbn`` package on PyPI.

    zxcvbn is the right baseline for this experiment for one specific reason:
    IndicPass borrowed its combinatorics. The ``k!``, the additive structure
    floor and the case-variation rule are all zxcvbn's, deliberately, so that a
    difference between the two estimators is attributable to the **lexicon**
    rather than to two unrelated formulas.

    Where they do differ is recorded rather than smoothed over. zxcvbn charges
    a flat 10 guesses per character for an unexplained span; IndicPass charges
    the observed character-class cardinality by default. On random strings that
    alone separates them by orders of magnitude, for reasons that have nothing
    to do with Indic awareness -- which is why
    ``results/reports/guess_model_sensitivity.md`` reports the benchmark under
    both policies.

    zxcvbn's own wordlists are not Indic, but they are not innocent of Indic
    words either: ``namaste``, ``bharat``, ``krishna`` and ``sharma`` are all in
    its English/name lists. The benchmark measures that overlap instead of
    assuming it away.
    """

    name = "zxcvbn"

    def __init__(self) -> None:
        try:
            import zxcvbn
        except ImportError as exc:  # pragma: no cover - environment-dependent
            raise BaselineUnavailable(
                "The 'zxcvbn' package is not installed, so the baseline cannot run.\n"
                "    python -m pip install -r requirements/base.txt\n"
                "Or set baseline.enabled: false in config/password.yaml -- and then no "
                "comparative claim may be made."
            ) from exc

        import importlib.metadata as metadata

        self._zxcvbn = zxcvbn
        self.version = metadata.version("zxcvbn")

    def estimate(self, password: str) -> BaselineEstimate:
        result = self._zxcvbn.zxcvbn(password)

        guesses = float(result["guesses"])
        feedback = result.get("feedback") or {}
        messages = [
            str(text)
            for text in [feedback.get("warning"), *(feedback.get("suggestions") or [])]
            if text
        ]

        return BaselineEstimate(
            guesses=guesses,
            log10_guesses=float(result.get("guesses_log10") or _log10(guesses)),
            score=int(result["score"]),
            # `pattern` is a name like "dictionary" or "date". Every other key
            # in a sequence entry -- token, matched_word, sub, l33t -- is
            # password content and is deliberately not carried across.
            patterns=tuple(str(item.get("pattern", "?")) for item in result.get("sequence", [])),
            feedback=tuple(messages),
        )


def _log10(guesses: float) -> float:
    return math.log10(guesses) if guesses > 0 else 0.0


#: Registry of implementations, keyed by the ``baseline.implementation`` value
#: in ``config/password.yaml``.
_IMPLEMENTATIONS: dict[str, type[PasswordStrengthBaseline]] = {"zxcvbn": ZxcvbnBaseline}


def load_baseline(implementation: str) -> PasswordStrengthBaseline:
    """Construct the named baseline, or explain why it is not available."""
    factory = _IMPLEMENTATIONS.get(implementation)
    if factory is None:
        raise BaselineUnavailable(
            f"Unknown baseline {implementation!r}. Available: {sorted(_IMPLEMENTATIONS)}."
        )
    return factory()
