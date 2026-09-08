"""Find the most probable derivation of a password under the grammar.

A dynamic programme over ``(position, segment count)``, the same shape as the
Milestone 2 segmentation search and for the same reason: the structure prior
``P(k)`` depends only on the number of segments, so carrying *k* in the state
lets it be applied once at the end instead of inside the recurrence.

What differs from Milestone 2 is what is being optimised. That search minimised
a *cost* built from wordlist positions and multipliers; this one maximises a
*probability* under a normalised model. The two are not the same operation
wearing different signs -- a cost of "position 41" is an assertion about an
attacker's wordlist, while a probability of ``10^-4.4`` is a statement about a
distribution that sums to one. Only the second can be turned into a guess
number by counting how many passwords outrank it, which is what
:mod:`indicpass.password.pcfg.estimator` then does.

Ambiguity is expected. ``bharat`` derives through ``word`` and through
``unknown``; ``2024`` through ``digits`` and through ``year``. Taking the
maximum is the right resolution for guessing: an attacker enumerating in
probability order reaches the password by whichever derivation is cheapest, and
never pays for the others.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from indicpass.password.mangling import case_transformation
from indicpass.password.patterns import is_digits, is_symbols, is_year
from indicpass.password.pcfg.grammar import (
    CATEGORY_DIGITS,
    CATEGORY_SYMBOLS,
    CATEGORY_UNKNOWN,
    CATEGORY_WORD,
    CATEGORY_YEAR,
    PcfgGrammar,
)

__all__ = ["Derivation", "PcfgSegment", "best_derivation"]

_NEGATIVE_INFINITY = -math.inf


@dataclass(frozen=True)
class PcfgSegment:
    """One segment of a derivation.

    ``token`` is a piece of the password and is held in memory only.
    :meth:`describe` is the publishable form and never returns it -- the same
    redaction rule the Milestone 2 :class:`~indicpass.password.result.Match`
    follows, enforced here rather than at the serialisation boundary.
    """

    category: str
    start: int
    end: int
    token: str
    #: ``log10 P(terminal)``, casing included. Excludes the category prior.
    log10_terminal: float
    #: ``log10 P(category)``.
    log10_category: float
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> int:
        return self.end - self.start

    @property
    def log10_probability(self) -> float:
        return self.log10_terminal + self.log10_category

    def describe(self, *, include_token: bool = False) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "category": self.category,
            "start": self.start,
            "end": self.end,
            "length": self.length,
            "log10_terminal": round(self.log10_terminal, 4),
            "log10_category": round(self.log10_category, 4),
            "log10_probability": round(self.log10_probability, 4),
            **{key: value for key, value in self.detail.items() if key != "native_form"},
        }
        if include_token:
            payload["token"] = self.token
            if "native_form" in self.detail:
                payload["native_form"] = self.detail["native_form"]
        return payload


@dataclass(frozen=True)
class Derivation:
    """The winning parse, and the pieces a researcher needs to argue with it."""

    segments: tuple[PcfgSegment, ...]
    #: ``log10 P(password)`` under the grammar: structure, categories, terminals.
    log10_probability: float
    #: ``log10 P(k)`` alone, so the structure prior's contribution is visible
    #: rather than folded invisibly into the total.
    log10_structure: float
    #: True when no derivation covers the password at all -- an unsupported
    #: character, or one needing more segments than ``max_segments`` allows.
    supported: bool = True

    @property
    def structure(self) -> tuple[str, ...]:
        """The category sequence, e.g. ``("word", "year")``."""
        return tuple(segment.category for segment in self.segments)

    def describe(self, *, include_tokens: bool = False) -> dict[str, Any]:
        return {
            "structure": list(self.structure),
            "segments": [s.describe(include_token=include_tokens) for s in self.segments],
            "log10_probability": round(self.log10_probability, 6),
            "log10_structure_prior": round(self.log10_structure, 6),
            "supported": self.supported,
        }


def _candidates(grammar: PcfgGrammar, password: str) -> list[PcfgSegment]:
    """Every span the grammar can derive, in every category that admits it.

    Offered, not chosen. The parser decides which survive, exactly as the
    Milestone 2 matcher offers spans for the segmentation search to reject.
    """
    length = len(password)
    limit = grammar.settings.max_run_length
    found: list[PcfgSegment] = []

    for start in range(length):
        for end in range(start + 1, min(start + limit, length) + 1):
            token = password[start:end]

            if token.isalpha() and token.isascii():
                log10, entry = grammar.log10_word(token)
                if log10 != _NEGATIVE_INFINITY and entry is not None:
                    found.append(
                        PcfgSegment(
                            category=CATEGORY_WORD,
                            start=start,
                            end=end,
                            token=token,
                            log10_terminal=log10,
                            log10_category=grammar.log10_category(CATEGORY_WORD),
                            detail={
                                "language": entry.language,
                                "tier": entry.tier,
                                "rank": entry.rank,
                                "frequency": entry.frequency,
                                "frequency_source": entry.frequency_source,
                                "observed_frequency": entry.frequency is not None,
                                "model_verified": entry.model_verified,
                                "case_transformation": case_transformation(token),
                                "native_form": entry.native_form,
                            },
                        )
                    )

                unknown = grammar.log10_unknown(token)
                if unknown != _NEGATIVE_INFINITY:
                    found.append(
                        PcfgSegment(
                            category=CATEGORY_UNKNOWN,
                            start=start,
                            end=end,
                            token=token,
                            log10_terminal=unknown,
                            log10_category=grammar.log10_category(CATEGORY_UNKNOWN),
                            detail={
                                "case_transformation": case_transformation(token),
                                "ngram_order": grammar.settings.ngram_order,
                            },
                        )
                    )
                continue

            if is_digits(token):
                digits = grammar.log10_digits(token)
                if digits != _NEGATIVE_INFINITY:
                    found.append(
                        PcfgSegment(
                            category=CATEGORY_DIGITS,
                            start=start,
                            end=end,
                            token=token,
                            log10_terminal=digits,
                            log10_category=grammar.log10_category(CATEGORY_DIGITS),
                            detail={"length": end - start},
                        )
                    )
                if is_year(token, grammar.settings.year_range):
                    found.append(
                        PcfgSegment(
                            category=CATEGORY_YEAR,
                            start=start,
                            end=end,
                            token=token,
                            log10_terminal=grammar.log10_year(),
                            log10_category=grammar.log10_category(CATEGORY_YEAR),
                            detail={"year_range": list(grammar.settings.year_range)},
                        )
                    )
                continue

            if is_symbols(token):
                symbols = grammar.log10_symbols(token)
                if symbols != _NEGATIVE_INFINITY:
                    found.append(
                        PcfgSegment(
                            category=CATEGORY_SYMBOLS,
                            start=start,
                            end=end,
                            token=token,
                            log10_terminal=symbols,
                            log10_category=grammar.log10_category(CATEGORY_SYMBOLS),
                            detail={"length": end - start},
                        )
                    )
    return found


def best_derivation(grammar: PcfgGrammar, password: str) -> Derivation:
    """The maximum-probability derivation of *password*, or an unsupported one.

    Returns ``supported=False`` with ``log10_probability = -inf`` when the
    grammar cannot cover the password -- a character outside every terminal
    alphabet, or a password needing more segments than the prior allows. The
    caller must not read that as "very strong": an unsupported password is one
    this model says nothing about, and the estimator falls back accordingly.
    """
    length = len(password)
    if length == 0:
        return Derivation(segments=(), log10_probability=_NEGATIVE_INFINITY,
                          log10_structure=_NEGATIVE_INFINITY, supported=False)

    depth = max(1, min(grammar.settings.max_segments, length))
    candidates = _candidates(grammar, password)

    best = [[_NEGATIVE_INFINITY] * (depth + 1) for _ in range(length + 1)]
    parent: list[list[tuple[int, int, PcfgSegment] | None]] = [
        [None] * (depth + 1) for _ in range(length + 1)
    ]
    best[0][0] = 0.0

    # Sorting by end position makes one pass sufficient: every segment ending
    # at j starts strictly before j, so best[start] is already final.
    for segment in sorted(candidates, key=lambda s: (s.end, s.start)):
        contribution = segment.log10_probability
        if contribution == _NEGATIVE_INFINITY:
            continue
        for count in range(depth):
            previous = best[segment.start][count]
            if previous == _NEGATIVE_INFINITY:
                continue
            total = previous + contribution
            if total > best[segment.end][count + 1]:
                best[segment.end][count + 1] = total
                parent[segment.end][count + 1] = (segment.start, count, segment)

    winning_k = -1
    winning_total = _NEGATIVE_INFINITY
    winning_structure = _NEGATIVE_INFINITY
    for count in range(1, depth + 1):
        if best[length][count] == _NEGATIVE_INFINITY:
            continue
        prior = grammar.log10_structure(count)
        if prior == _NEGATIVE_INFINITY:
            continue
        total = best[length][count] + prior
        if total > winning_total:
            winning_total, winning_k, winning_structure = total, count, prior

    if winning_k < 0:
        return Derivation(segments=(), log10_probability=_NEGATIVE_INFINITY,
                          log10_structure=_NEGATIVE_INFINITY, supported=False)

    chain: list[PcfgSegment] = []
    position, count = length, winning_k
    while count > 0:
        step = parent[position][count]
        assert step is not None
        position, count, segment = step
        chain.append(segment)
    chain.reverse()

    return Derivation(
        segments=tuple(chain),
        log10_probability=winning_total,
        log10_structure=winning_structure,
        supported=True,
    )


def structure_of(segments: Sequence[PcfgSegment]) -> str:  # pragma: no cover - display
    """``"word+year"`` -- a compact label for a derivation's shape."""
    return "+".join(segment.category for segment in segments)
