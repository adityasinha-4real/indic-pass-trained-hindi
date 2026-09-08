"""The structured result of scoring one password.

Two rules shape this module.

**Guesses, not entropy.** The primary quantity is ``guess_number``: how many
attempts the modelled attacker makes before reaching this password.
``log10_guesses`` is its base-10 logarithm and nothing more. Neither is called
entropy anywhere, because neither is one -- see
``docs/password_strength_design.md``.

**The password is never written down.** A result carries the password's
*length* and a description of the patterns found in it, and the matched
substrings are held in memory only. :meth:`PasswordStrengthResult.to_dict`
redacts them by default, so the obvious way to serialise a result is also the
safe way; a caller has to pass ``include_tokens=True`` on purpose, and only the
interactive CLI does, printing to a terminal rather than a file.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from indicpass.password.baseline import BaselineEstimate
    from indicpass.password.pcfg.estimator import PcfgEstimate

__all__ = [
    "Match",
    "PasswordStrengthResult",
    "log10_guesses",
]


def log10_guesses(guesses: float) -> float:
    """``log10`` of a guess count, floored at zero guesses -> 0.0.

    Defined here rather than inlined so that every consumer -- meter, CLI,
    benchmark -- agrees on what happens at the bottom of the range.
    """
    if guesses == math.inf:
        return math.inf
    return math.log10(guesses) if guesses > 0 else 0.0


#: Detail keys that give the password away as surely as the token does.
#: ``native_form`` is the Devanagari rendering of the matched substring, and
#: anyone holding the dictionary can map it straight back to the Roman
#: spelling -- so it is redacted with the token, not published beside it.
TOKEN_EQUIVALENT_DETAIL: frozenset[str] = frozenset({"native_form"})

#: Significant figures kept when a guess count is serialised. The estimate
#: spans thirty orders of magnitude and is accurate to none of its trailing
#: digits; printing ``3524551264.000004`` invites a reader to believe sixteen.
_GUESS_SIGNIFICANT_FIGURES = 6


def round_guesses(value: float) -> float:
    """Round a guess count to :data:`_GUESS_SIGNIFICANT_FIGURES` significant figures."""
    if value in (0.0, math.inf) or math.isnan(value):
        return value
    digits = _GUESS_SIGNIFICANT_FIGURES - 1 - math.floor(math.log10(abs(value)))
    return round(value, digits)


def guesses_from_log10(value: float) -> float:
    """``10 ** value``, returning ``inf`` rather than raising on overflow.

    A 200-character random password really does exceed the largest float, and
    a meter that crashes on one is worse than a meter that says "more than
    astronomically many". ``log10_guesses`` stays exact either way, which is
    why it, not this, is the field the analysis uses.
    """
    try:
        return 10.0**value
    except OverflowError:
        return math.inf


@dataclass(frozen=True)
class Match:
    """One explained span of a password.

    A match says: characters ``[start, end)`` look like *pattern*, and an
    attacker enumerating that pattern reaches them in about ``10 ** cost``
    tries.

    The cost is stored as a **logarithm**, not as a count. A 40-character
    unexplained span costs 26**40 guesses, which is a perfectly meaningful
    number and not a representable float; storing the log means the search can
    compare such spans instead of raising ``OverflowError`` on one. ``guesses``
    remains available as a property for display, and reads ``inf`` where the
    count genuinely exceeds a float.

    ``token`` is the literal substring. It is part of the password, so it is
    subject to the redaction rule described in this module's docstring.
    """

    pattern: str  # indic_word | digits | year | symbols | repeat | bruteforce
    start: int
    end: int
    token: str
    #: log10 of the guesses this span costs. Authoritative.
    cost: float
    #: Pattern-specific provenance: dictionary tier, case transformation, and
    #: so on. Keys named in :data:`TOKEN_EQUIVALENT_DETAIL` are redacted along
    #: with the token; everything else describes the span's shape and is safe.
    detail: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_guesses(
        cls,
        pattern: str,
        start: int,
        end: int,
        token: str,
        guesses: float,
        detail: dict[str, Any] | None = None,
    ) -> Match:
        """Build a match from a guess *count* rather than its logarithm.

        For the patterns whose cost is small and naturally expressed as a
        count -- a year window, a tier position. Spans whose cost can overflow
        compute the log directly instead.
        """
        return cls(
            pattern=pattern,
            start=start,
            end=end,
            token=token,
            cost=log10_guesses(guesses),
            detail=detail or {},
        )

    @property
    def guesses(self) -> float:
        return guesses_from_log10(self.cost)

    @property
    def length(self) -> int:
        return self.end - self.start

    def describe(self, *, include_token: bool = False) -> dict[str, Any]:
        detail = (
            self.detail
            if include_token
            else {k: v for k, v in self.detail.items() if k not in TOKEN_EQUIVALENT_DETAIL}
        )
        payload: dict[str, Any] = {
            "pattern": self.pattern,
            "start": self.start,
            "end": self.end,
            "length": self.length,
            "guesses": round_guesses(self.guesses),
            "log10_guesses": round(self.cost, 4),
            **detail,
        }
        if include_token:
            payload["token"] = self.token
        return payload


@dataclass(frozen=True)
class PasswordStrengthResult:
    """Everything the meter concluded about one password.

    ``indicpass_guesses`` / ``indicpass_score`` duplicate ``guess_number`` /
    ``strength_score`` deliberately. The comparison harness writes rows holding
    several estimators side by side, and a column literally named for its
    estimator is far harder to misread later than a bare ``guesses`` that the
    reader has to remember the provenance of.
    """

    password_length: int
    guess_number: float
    #: Stored, not derived. The guess count overflows a float for very long
    #: random passwords; its logarithm never does, so this is the field the
    #: analysis and the 0-4 score are computed from.
    log10_guesses: float
    strength_score: int
    strength_label: str

    #: Every match in the winning segmentation, cheapest total first.
    matched_patterns: tuple[Match, ...] = ()
    #: Dictionary hits, in order of appearance.
    matched_indic_words: tuple[str, ...] = ()
    #: Dictionary hits that came from a named-entity tier.
    matched_names: tuple[str, ...] = ()
    #: Transformations detected on dictionary hits, e.g. ``"capitalized"``.
    matched_variants: tuple[str, ...] = ()

    #: Human-readable per-segment breakdown of where the guesses came from.
    estimated_components: tuple[dict[str, Any], ...] = ()
    #: Plain-language observations for the person choosing the password.
    warnings: tuple[str, ...] = ()

    #: The generic estimator's verdict on the same password, when one ran.
    #: ``None`` means no baseline was configured -- and then no comparative
    #: claim may be made from this result.
    baseline: BaselineEstimate | None = None
    #: Which baseline produced it, e.g. ``"zxcvbn"``. Names the nested block
    #: in :meth:`to_dict` so a stored row says what it was compared against.
    baseline_name: str = "baseline"

    #: The PCFG's verdict on the same password, when one was attached.
    #: ``None`` means no grammar ran. It is reported ALONGSIDE the fields above
    #: and never replaces them: ``guess_number`` remains the Milestone 2
    #: estimator's number, because swapping the primary estimator is a decision
    #: the comparison has to earn rather than a side effect of adding a model.
    pcfg: PcfgEstimate | None = None

    @property
    def indicpass_guesses(self) -> float:
        return self.guess_number

    @property
    def indicpass_score(self) -> int:
        return self.strength_score

    @property
    def baseline_guesses(self) -> float | None:
        return self.baseline.guesses if self.baseline else None

    @property
    def baseline_score(self) -> int | None:
        return self.baseline.score if self.baseline else None

    @property
    def baseline_log10_guesses(self) -> float | None:
        return self.baseline.log10_guesses if self.baseline else None

    @property
    def pcfg_log10_guesses(self) -> float | None:
        return self.pcfg.log10_guesses if self.pcfg else None

    @property
    def pcfg_score(self) -> int | None:
        return self.pcfg.score if self.pcfg else None

    @property
    def combined_log10_guesses(self) -> float:
        """The cheapest of every estimator that ran, on this password.

        Guessing cost is a minimum over the attacker's options, so an attacker
        holding all of these wordlists and models pays the smallest. This, and
        not any single column, is the number that describes the password.
        """
        candidates = [self.log10_guesses]
        if self.baseline is not None:
            candidates.append(self.baseline.log10_guesses)
        if self.pcfg is not None:
            candidates.append(self.pcfg.log10_guesses)
        return min(candidates)

    @property
    def has_indic_match(self) -> bool:
        return bool(self.matched_indic_words)

    def to_dict(self, *, include_tokens: bool = False) -> dict[str, Any]:
        """Serialise. Matched substrings are redacted unless asked for.

        ``include_tokens=True`` must never be used for anything written to
        disk: the matched tokens are pieces of the password.

        The payload carries the estimators both flat and nested. The nested
        ``indicpass`` / ``<baseline>`` blocks are the schema the benchmark
        writes, because a column named for its estimator cannot be misread six
        months later; the flat fields are what the CLI and the existing callers
        read. They are the same numbers, not two computations.
        """
        matches = [
            match.describe(include_token=include_tokens) for match in self.matched_patterns
        ]
        payload: dict[str, Any] = {
            "password_length": self.password_length,
            "guess_number": round_guesses(self.guess_number),
            "log10_guesses": round(self.log10_guesses, 6),
            "strength_score": self.strength_score,
            "strength_label": self.strength_label,
            "indicpass_guesses": round_guesses(self.indicpass_guesses),
            "indicpass_score": self.indicpass_score,
            "baseline_guesses": self.baseline_guesses,
            "baseline_score": self.baseline_score,
            "indicpass": {
                "guesses": round_guesses(self.guess_number),
                "log10_guesses": round(self.log10_guesses, 6),
                "score": self.strength_score,
                "label": self.strength_label,
                "matches": matches,
            },
            "matched_patterns": matches,
            "matched_indic_words": (
                list(self.matched_indic_words) if include_tokens else len(self.matched_indic_words)
            ),
            "matched_names": (
                list(self.matched_names) if include_tokens else len(self.matched_names)
            ),
            # Transformation names describe the password's shape, not its
            # content, so they are safe to write out either way.
            "matched_variants": list(self.matched_variants),
            "estimated_components": list(self.estimated_components),
            "warnings": list(self.warnings),
        }
        if self.baseline is not None:
            payload[self.baseline_name] = self.baseline.to_dict()
        if self.pcfg is not None:
            # A nested block of its own, never merged into the flat fields: a
            # reader must not be able to mistake the PCFG's number for the one
            # `guess_number` carries. Its segments arrive already redacted --
            # see IndicPassMeter.score.
            payload["pcfg"] = self.pcfg.to_dict()
            payload["combined_log10_guesses"] = round(self.combined_log10_guesses, 6)
        return payload
