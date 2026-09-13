"""Attack-budget success rates and guess-number distribution statistics.

This module knows nothing about :class:`~indicpass.password.validation.ValidationRow`
or any other research type -- it takes plain booleans, optional integers and
floats, so it can be unit-tested without constructing a meter, a dictionary or
an attack, and so it cannot accidentally import (and therefore cannot
accidentally depend on) anything under ``indicpass.password``.
:mod:`scripts.evaluate_model` is what bridges the two.

Ground truth for "crackable within budget B" is always

    covered AND rank is not None AND rank <= B

which is exactly section 3's suggested definition, applied to an **observed**
reference-attack rank (Milestone 4 or Milestone 5) rather than to anything an
estimator produced. An uncovered/unreachable target is never treated as
crackable: the attacker enumerated its whole budget and never reached it,
which is evidence the password was *not* cracked within any B smaller than
that attacker's own budget -- see ``docs/evaluation.md`` section 3 for why
this is not the same claim as "reachable if we had a bigger attacker".
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BUDGETS",
    "GuessNumberStats",
    "attack_budget_table",
    "crackable_within_budget",
    "guess_number_stats",
    "percentile",
]

#: Section 8's suggested budgets, in candidates. ``1e3``, ``1e6``, ``1e8`` and
#: ``1e10`` additionally coincide with ``config/password.yaml``'s existing
#: ``strength.thresholds`` -- frozen research constants set before and
#: independently of this evaluation, not fitted to it. See
#: ``docs/evaluation.md`` section 6 for why that overlap is what lets this
#: module report threshold-anchored classification metrics without tuning a
#: threshold on the test set.
BUDGETS: tuple[float, ...] = (1e3, 1e4, 1e5, 1e6, 1e8, 1e10)


def crackable_within_budget(covered: bool, rank: int | float | None, budget: float) -> bool:
    """``True`` iff an attacker that reached this password did so within *budget*."""
    if not covered or rank is None:
        return False
    return float(rank) <= budget


def attack_budget_table(
    covered: Sequence[bool],
    ranks: Sequence[int | float | None],
    *,
    budgets: Sequence[float] = BUDGETS,
) -> list[dict[str, Any]]:
    """Success rate at each budget, over the same population throughout.

    ``count`` is how many of *all* the targets (covered or not) were cracked
    within that budget -- an uncovered target lowers the rate rather than
    being excluded, because "uncovered" is itself evidence about this
    attacker's reach and dropping it would silently condition the rate on
    coverage.
    """
    if len(covered) != len(ranks):
        raise ValueError(f"covered has {len(covered)} entries, ranks has {len(ranks)}.")
    total = len(covered)
    rows: list[dict[str, Any]] = []
    for budget in budgets:
        count = sum(
            1
            for c, r in zip(covered, ranks, strict=True)
            if crackable_within_budget(c, r, budget)
        )
        rows.append(
            {
                "budget": budget,
                "log10_budget": round(math.log10(budget), 4) if budget > 0 else None,
                "count": count,
                "total": total,
                "success_rate": (count / total) if total else None,
            }
        )
    return rows


def percentile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation percentile of an already-sorted sequence, ``q`` in ``[0, 1]``.

    Written locally rather than reaching for :func:`statistics.quantiles`
    because that function fixes the number of equally spaced cut points
    rather than accepting an arbitrary ``q``, and its default method
    (exclusive) disagrees with the widely-used linear/inclusive convention
    this evaluation reports under. Deterministic, and tested directly against
    hand-computed values in ``tests/test_evaluation_budgets.py``.
    """
    if not sorted_values:
        raise ValueError("percentile of an empty sequence is undefined.")
    if not 0.0 <= q <= 1.0:
        raise ValueError(f"q must be in [0, 1], got {q}.")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = q * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * fraction


@dataclass(frozen=True)
class GuessNumberStats:
    """Summary of a set of ``log10`` guess/rank values, plus the linear-space reading.

    Everything is computed in ``log10`` space -- the same reasoning
    :mod:`indicpass.password.experiment` gives: a mean over values spanning
    sixteen orders of magnitude is otherwise dominated by the largest few. The
    "geometric mean" of the underlying guess counts is, by definition,
    ``10 ** mean(log10 values))``, so it falls out of the same computation
    rather than needing :func:`statistics.geometric_mean` on numbers many of
    which do not fit in a float.
    """

    source: str
    samples: int
    excluded_non_finite: int
    median_log10: float | None
    geometric_mean_log10: float | None
    quantiles_log10: dict[str, float | None]
    median: float | None
    geometric_mean: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "samples": self.samples,
            "excluded_non_finite": self.excluded_non_finite,
            "median_log10": self.median_log10,
            "geometric_mean_log10": self.geometric_mean_log10,
            "quantiles_log10": self.quantiles_log10,
            "median": self.median,
            "geometric_mean": self.geometric_mean,
            "note": (
                f"{self.source}: 'estimated' means an IndicPass/PCFG/baseline guess "
                "number (a model output); 'observed' means a reference-attack rank "
                "(Milestone 4 or 5, a fact about one specific attacker). The two are "
                "never averaged together."
            ),
        }


_QUANTILE_POINTS: tuple[float, ...] = (0.1, 0.25, 0.5, 0.75, 0.9)


def guess_number_stats(log10_values: Sequence[float], *, source: str) -> GuessNumberStats:
    """Median, geometric mean and quantiles of *log10_values*.

    *source* must be either ``"estimated"`` (a model's ``log10_guesses``) or
    ``"observed"`` (an attack's ``log10_rank``) and is carried into every
    output so a report can never present one as the other.
    """
    if source not in {"estimated", "observed"}:
        raise ValueError(f"source must be 'estimated' or 'observed', got {source!r}.")
    finite = sorted(v for v in log10_values if math.isfinite(v))
    excluded = len(log10_values) - len(finite)
    if not finite:
        return GuessNumberStats(
            source=source,
            samples=0,
            excluded_non_finite=excluded,
            median_log10=None,
            geometric_mean_log10=None,
            quantiles_log10=dict.fromkeys(f"p{int(q * 100)}" for q in _QUANTILE_POINTS),
            median=None,
            geometric_mean=None,
        )
    median_log10 = statistics.median(finite)
    mean_log10 = statistics.fmean(finite)
    quantiles = {f"p{int(q * 100)}": round(percentile(finite, q), 6) for q in _QUANTILE_POINTS}

    def _to_linear(value: float) -> float | None:
        try:
            return 10.0**value
        except OverflowError:
            return math.inf

    return GuessNumberStats(
        source=source,
        samples=len(finite),
        excluded_non_finite=excluded,
        median_log10=round(median_log10, 6),
        geometric_mean_log10=round(mean_log10, 6),
        quantiles_log10=quantiles,
        median=_to_linear(median_log10),
        geometric_mean=_to_linear(mean_log10),
    )
