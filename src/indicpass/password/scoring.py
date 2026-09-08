"""Turn a bag of matches into one guess number, and that number into 0-4.

The guess model
---------------
An attacker who has decided a password is "a word then some digits" must do
three things: enumerate the structures, enumerate each slot, and try the
orderings. For a segmentation ``S = (m_1 .. m_k)`` covering the whole password:

    G(S) = k! * prod_i g(m_i)  +  D^(k-1)

* ``prod g(m_i)`` -- the attacker enumerates each segment independently.
* ``k!`` -- the orderings of those k segments.
* ``D^(k-1)`` -- the cost of reaching a k-segment structure at all. ``D`` is
  ``scoring.structure_factor``.

The structure term is **added, not multiplied**. It is a floor: an attacker
who splits a password into k pieces has to work through the structures of that
shape first, so a k-piece explanation cannot cost less than ``D^(k-1)`` however
cheap its pieces are. Multiplying instead would make the term compound, and a
three-piece reading of ``sharma@123`` would end up costing more than calling
the last four characters random -- the meter would discard an explanation it
had already found. Adding keeps the penalty bounded and lets the true
decomposition win.

The reported estimate is the attacker's best case:

    guess_number = min over all S of G(S)

taking the minimum is what makes this attack-oriented. A password is only as
strong as its cheapest explanation, so finding a *better* explanation can only
ever lower the estimate -- adding the Indic dictionary can never make a
password look stronger than it did without it. That is the property the
Milestone 2 comparison rests on.

``D``, ``k!`` and the additive form are the same as zxcvbn's. That is
deliberate: holding the combinatorics identical means the Milestone 2
comparison measures the effect of the Indic lexicon rather than the effect of
two unrelated formulas. It also means IndicPass is not an independent
estimator, and the write-up has to say so.

Everything is computed in log10 space. The products overflow a float long
before a password gets unreasonable, and ``log10_guesses`` is the quantity the
analysis wants anyway.

This is not entropy
-------------------
``log10_guesses`` is the logarithm of a search cost under one specific attacker
model. It is not the entropy of a probability distribution over passwords -- no
such distribution is estimated anywhere in this module -- so nothing here calls
it that. See ``docs/password_strength_design.md``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any

from indicpass.password.patterns import bruteforce_log10_guesses, observed_cardinality
from indicpass.password.result import Match, guesses_from_log10

__all__ = [
    "ScoringSettings",
    "Segmentation",
    "StrengthScale",
    "best_segmentation",
]


@dataclass(frozen=True)
class ScoringSettings:
    """Everything the guess model reads from ``config/password.yaml``."""

    structure_factor: float
    min_guesses: float
    max_segmentation_depth: int
    #: Either the string ``"observed"`` or a fixed integer cardinality.
    bruteforce_cardinality: str | int
    character_class_sizes: Mapping[str, int]

    @classmethod
    def from_config(
        cls, scoring: Mapping[str, Any], matching: Mapping[str, Any]
    ) -> ScoringSettings:
        raw = scoring.get("bruteforce_cardinality", "observed")
        cardinality: str | int = "observed" if raw == "observed" else int(raw)
        return cls(
            structure_factor=float(scoring.get("structure_factor", 10000)),
            min_guesses=float(scoring.get("min_guesses", 1.0)),
            max_segmentation_depth=int(matching.get("max_segmentation_depth", 12)),
            bruteforce_cardinality=cardinality,
            character_class_sizes=dict(scoring.get("character_class_sizes") or {}),
        )

    def cardinality_for(self, password: str) -> int:
        """Resolve the bruteforce alphabet size for one password."""
        if self.bruteforce_cardinality == "observed":
            return observed_cardinality(password, self.character_class_sizes)
        return max(int(self.bruteforce_cardinality), 1)


@dataclass(frozen=True)
class Segmentation:
    """The cheapest way found to explain a password end to end."""

    matches: tuple[Match, ...]
    log10_guesses: float

    @property
    def guess_number(self) -> float:
        return guesses_from_log10(self.log10_guesses)


class StrengthScale:
    """The configured 0-4 band boundaries, in guesses.

    A password scores the number of thresholds it reaches. Four thresholds
    therefore give five bands, and the labels list must have one more entry
    than the thresholds list -- checked here rather than discovered later as an
    IndexError on an unusual password.

    The comparison is done in log10 space so that a password whose guess count
    overflowed a float still lands in the top band instead of raising.
    """

    def __init__(self, thresholds: Sequence[float], labels: Sequence[str]) -> None:
        if not thresholds:
            raise ValueError("The strength scale needs at least one threshold.")
        if len(labels) != len(thresholds) + 1:
            raise ValueError(
                f"{len(thresholds)} thresholds need {len(thresholds) + 1} labels, "
                f"got {len(labels)}."
            )
        ordered = [float(value) for value in thresholds]
        if any(b <= a for a, b in pairwise(ordered)):
            raise ValueError(f"Strength thresholds must strictly increase; got {ordered}.")
        if any(value <= 0 for value in ordered):
            raise ValueError(f"Strength thresholds must be positive guess counts; got {ordered}.")

        self.thresholds = tuple(ordered)
        self.labels = tuple(str(label) for label in labels)
        self._log_thresholds = tuple(math.log10(value) for value in ordered)

    @classmethod
    def from_config(cls, strength: Mapping[str, Any]) -> StrengthScale:
        return cls(strength.get("thresholds") or [], strength.get("labels") or [])

    def score(self, log10_guesses: float) -> int:
        """How many thresholds this many guesses reaches: 0 .. len(thresholds)."""
        return sum(1 for limit in self._log_thresholds if log10_guesses >= limit)

    def label(self, score: int) -> str:
        return self.labels[max(0, min(score, len(self.labels) - 1))]


def _log10_add(a: float, b: float) -> float:
    """``log10(10**a + 10**b)``, without ever forming either power.

    The guess model adds a structure floor to a product, and both can be far
    outside a float's range. Factoring out the larger term keeps the sum exact
    where it matters and finite where it does not.
    """
    if a == math.inf or b == math.inf:
        return math.inf
    high, low = (a, b) if a >= b else (b, a)
    return high + math.log10(1.0 + 10.0 ** (low - high))


def _bruteforce_matches(password: str, settings: ScoringSettings) -> list[Match]:
    """A fallback match for every span, so the search always has a covering.

    Without these a password containing an unrecognised character would have no
    valid segmentation at all. Offering *every* span rather than only maximal
    gaps costs O(L^2) and lets the search merge adjacent unexplained runs, which
    it always prefers: two spans cost ``2! * D * C^a * C^b`` against ``C^(a+b)``
    for one, and ``D`` is large.
    """
    cardinality = settings.cardinality_for(password)
    matches: list[Match] = []
    for start in range(len(password)):
        for end in range(start + 1, len(password) + 1):
            token = password[start:end]
            matches.append(
                Match(
                    pattern="bruteforce",
                    start=start,
                    end=end,
                    token=token,
                    cost=bruteforce_log10_guesses(token, cardinality=cardinality),
                    detail={"length": end - start, "cardinality": cardinality},
                )
            )
    return matches


def best_segmentation(
    password: str,
    matches: Sequence[Match],
    settings: ScoringSettings,
) -> Segmentation:
    """Cheapest covering of *password*, by the model in this module's docstring.

    Dynamic programme over ``(position, segment count)``: ``best[j][k]`` is the
    smallest achievable ``sum log10 g(m)`` covering ``[0, j)`` with exactly *k*
    segments. The ``k!`` and ``D^(k-1)`` terms depend only on *k*, so they are
    applied once at the end rather than inside the recurrence.

    Without a covering there would be no estimate at all, so a bruteforce span
    is offered for every substring; the search is therefore never empty, and
    ``max_segmentation_depth`` can only ever raise the estimate.
    """
    length = len(password)
    if length == 0:
        floor = math.log10(max(settings.min_guesses, 1.0))
        return Segmentation(matches=(), log10_guesses=floor)

    depth = max(1, min(settings.max_segmentation_depth, length))
    candidates = [*matches, *_bruteforce_matches(password, settings)]

    infinity = math.inf
    # best[j][k]; k ranges 0..depth.
    best = [[infinity] * (depth + 1) for _ in range(length + 1)]
    parent: list[list[tuple[int, int, Match] | None]] = [
        [None] * (depth + 1) for _ in range(length + 1)
    ]
    best[0][0] = 0.0

    # Ordering by end position is what makes one pass sufficient: every match
    # ending at j starts strictly before j, so best[start] is already final.
    for match in sorted(candidates, key=lambda m: (m.end, m.start)):
        # A match's cost is already a log10, and is floored at zero: a pattern
        # cannot make a password cheaper than free.
        cost = max(match.cost, 0.0)
        for count in range(depth):
            previous = best[match.start][count]
            if previous == infinity:
                continue
            total = previous + cost
            if total < best[match.end][count + 1]:
                best[match.end][count + 1] = total
                parent[match.end][count + 1] = (match.start, count, match)

    # The structure term depends only on k, so minimising the product for each
    # k separately and combining afterwards is exact -- which is the reason k
    # is carried in the DP state rather than collapsed.
    winning_k = -1
    winning_total = infinity
    for count in range(1, depth + 1):
        if best[length][count] == infinity:
            continue
        total = _log10_add(
            math.log10(math.factorial(count)) + best[length][count],
            (count - 1) * math.log10(settings.structure_factor),
        )
        if total < winning_total:
            winning_total, winning_k = total, count

    if winning_k < 0:  # pragma: no cover - bruteforce spans make this unreachable
        raise RuntimeError(f"No segmentation covers a password of length {length}.")

    chain: list[Match] = []
    position, count = length, winning_k
    while count > 0:
        step = parent[position][count]
        assert step is not None
        position, count, match = step
        chain.append(match)
    chain.reverse()

    floor = math.log10(max(settings.min_guesses, 1.0))
    return Segmentation(matches=tuple(chain), log10_guesses=max(winning_total, floor))
