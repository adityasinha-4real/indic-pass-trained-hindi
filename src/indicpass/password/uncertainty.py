"""Confidence intervals for the numbers this project reports.

Every metric in Milestones 2, 3 and 4 is a point estimate over a few hundred
generated samples, and none of them carries an interval. On the full 1,400 that
was tolerable. This milestone slices the same corpus into partitions of eighty
or ninety targets and then asks which of two estimators is better on one of
them, which is exactly the situation where a point estimate stops meaning
anything on its own.

So the primary metrics get a **percentile bootstrap**: resample the targets with
replacement, recompute, and report the 2.5th and 97.5th percentiles of the
resulting distribution. It assumes only that the targets are exchangeable within
the population being resampled -- which is what the benchmark generator makes
them, since it draws each one independently from the same word bank.

The paired difference is the point
----------------------------------
"Is the PCFG better than IndicPass on out-of-lexicon targets" is a question
about a *difference*, and two overlapping intervals do not answer it: the two
estimators are scored on the **same** targets, so their errors are correlated
and the interval on the difference is narrower than the overlap suggests.
:func:`bootstrap_group` therefore draws each resample once and scores every
estimator on it, so the differences it reports are paired by construction.

Nothing here converts an interval into a verdict. A difference whose interval
excludes zero is reported as exactly that -- with the effect size beside it --
and never as a significance claim. The corpus is one generated benchmark scored
against one attacker; the interval describes sampling variation within it and
nothing outside it.
"""

from __future__ import annotations

import math
import random
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from indicpass.password.validation import pearson, spearman

__all__ = [
    "BOOTSTRAP_STATISTICS",
    "Interval",
    "bootstrap_group",
    "compute_statistics",
]

#: The statistics an interval is produced for, and which direction is better.
#: Written down beside them so a report cannot announce a winner by maximising
#: an error, the same rule :data:`indicpass.password.validation.METRIC_DIRECTION`
#: enforces for the point estimates.
BOOTSTRAP_STATISTICS: Mapping[str, bool] = {
    "spearman": True,
    "pearson": True,
    "mean_absolute_error": False,
    "rmse": False,
    "within_1.0_log10": True,
    "calibration_slope": True,
    "r_squared": True,
}


@dataclass(frozen=True)
class Interval:
    """A statistic, its bootstrap interval, and what was resampled to get it.

    ``low`` and ``high`` are ``None`` when the population was too small for the
    interval to mean anything, and the point estimate is still reported. A
    missing interval is an absence of evidence and is shown as one, never as a
    zero-width one.
    """

    statistic: str
    point: float | None
    low: float | None
    high: float | None
    samples: int
    resamples: int
    confidence: float
    higher_is_better: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "statistic": self.statistic,
            "point": self.point,
            "ci_low": self.low,
            "ci_high": self.high,
            "samples": self.samples,
            "resamples": self.resamples,
            "confidence": self.confidence,
            "higher_is_better": self.higher_is_better,
            "excludes_zero": (
                None
                if self.low is None or self.high is None
                else bool(self.low > 0.0 or self.high < 0.0)
            ),
        }


def _round(value: float | None, digits: int = 4) -> float | None:
    return None if value is None else round(value, digits)


def compute_statistics(
    predicted: Sequence[float], observed: Sequence[float]
) -> dict[str, float | None]:
    """Every bootstrapped statistic, on one sample.

    One function rather than seven so a resample is scored in a single pass:
    the errors, the ranks and the least-squares fit are each computed once and
    shared. ``None`` where a statistic is undefined -- a constant series has no
    correlation, and reporting that as zero would be a claim.
    """
    count = len(predicted)
    if count == 0:
        return dict.fromkeys(BOOTSTRAP_STATISTICS)

    errors = [p - o for p, o in zip(predicted, observed, strict=True)]
    absolute = [abs(value) for value in errors]

    mean_x = statistics.fmean(predicted)
    mean_y = statistics.fmean(observed)
    variance = sum((x - mean_x) ** 2 for x in predicted)
    correlation = pearson(predicted, observed) if count > 1 else None
    if variance == 0.0:
        slope = None
    else:
        covariance = sum(
            (x - mean_x) * (y - mean_y) for x, y in zip(predicted, observed, strict=True)
        )
        slope = covariance / variance

    return {
        "spearman": spearman(predicted, observed) if count > 1 else None,
        "pearson": correlation,
        "mean_absolute_error": statistics.fmean(absolute),
        "rmse": math.sqrt(statistics.fmean([value * value for value in errors])),
        "within_1.0_log10": sum(1 for value in absolute if value <= 1.0) / count,
        "calibration_slope": slope,
        "r_squared": None if correlation is None else correlation**2,
    }


def _percentiles(values: Sequence[float], confidence: float) -> tuple[float, float]:
    ordered = sorted(values)
    tail = (1.0 - confidence) / 2.0
    count = len(ordered)
    low = ordered[min(count - 1, max(0, math.floor(tail * count)))]
    high = ordered[min(count - 1, max(0, math.ceil((1.0 - tail) * count) - 1))]
    return low, high


def bootstrap_group(
    observed: Sequence[float],
    predictions: Mapping[str, Sequence[float]],
    *,
    pairs: Sequence[tuple[str, str]] = (),
    seed: int = 42,
    resamples: int = 2000,
    confidence: float = 0.95,
    min_samples: int = 20,
    label: str = "",
) -> dict[str, Any]:
    """Intervals for every estimator, and for the named paired differences.

    The resample indices are drawn **once per call** and reused for every
    estimator and every pair, which is what makes ``pairs`` a paired bootstrap:
    both estimators in a pair see the same targets in the same resample, so the
    interval is on their difference rather than on two independent quantities.

    *label* seeds the generator alongside *seed*, so adding a population to the
    report leaves every other population's draws untouched.
    """
    count = len(observed)
    for name, values in predictions.items():
        if len(values) != count:
            raise ValueError(
                f"Estimator {name!r} has {len(values)} predictions for {count} targets."
            )

    points = {
        name: compute_statistics(values, observed) for name, values in predictions.items()
    }

    if count < min_samples or resamples <= 0:
        return {
            "samples": count,
            "resamples": 0,
            "confidence": confidence,
            "below_minimum": count < min_samples,
            "minimum_samples": min_samples,
            "estimators": {
                name: {
                    statistic: Interval(
                        statistic=statistic,
                        point=_round(values[statistic]),
                        low=None,
                        high=None,
                        samples=count,
                        resamples=0,
                        confidence=confidence,
                        higher_is_better=BOOTSTRAP_STATISTICS[statistic],
                    ).to_dict()
                    for statistic in BOOTSTRAP_STATISTICS
                }
                for name, values in points.items()
            },
            "differences": {
                f"{a}-minus-{b}": {
                    statistic: Interval(
                        statistic=statistic,
                        point=_difference(points, a, b, statistic),
                        low=None,
                        high=None,
                        samples=count,
                        resamples=0,
                        confidence=confidence,
                        higher_is_better=BOOTSTRAP_STATISTICS[statistic],
                    ).to_dict()
                    for statistic in BOOTSTRAP_STATISTICS
                }
                for a, b in pairs
                if a in points and b in points
            },
            "note": (
                f"Fewer than {min_samples} targets: point estimates only. An interval "
                "over a population this small would be wider than the quantity it "
                "describes and is not reported."
            ),
        }

    rng = random.Random(f"bootstrap:{seed}:{label}")
    draws: dict[str, dict[str, list[float]]] = {
        name: {statistic: [] for statistic in BOOTSTRAP_STATISTICS} for name in predictions
    }
    difference_draws: dict[str, dict[str, list[float]]] = {
        f"{a}-minus-{b}": {statistic: [] for statistic in BOOTSTRAP_STATISTICS}
        for a, b in pairs
        if a in predictions and b in predictions
    }

    for _ in range(resamples):
        indices = [rng.randrange(count) for _ in range(count)]
        resampled_observed = [observed[index] for index in indices]
        scored: dict[str, dict[str, float | None]] = {}
        for name, values in predictions.items():
            scored[name] = compute_statistics(
                [values[index] for index in indices], resampled_observed
            )
            for statistic, value in scored[name].items():
                if value is not None:
                    draws[name][statistic].append(value)
        for key in difference_draws:
            first, second = key.split("-minus-")
            for statistic in BOOTSTRAP_STATISTICS:
                left, right = scored[first][statistic], scored[second][statistic]
                if left is not None and right is not None:
                    difference_draws[key][statistic].append(left - right)

    return {
        "samples": count,
        "resamples": resamples,
        "confidence": confidence,
        "below_minimum": False,
        "minimum_samples": min_samples,
        "estimators": {
            name: {
                statistic: _interval(
                    statistic, points[name][statistic], draws[name][statistic],
                    count, resamples, confidence,
                )
                for statistic in BOOTSTRAP_STATISTICS
            }
            for name in predictions
        },
        "differences": {
            key: {
                statistic: _interval(
                    statistic,
                    _difference(points, *key.split("-minus-"), statistic),
                    difference_draws[key][statistic],
                    count,
                    resamples,
                    confidence,
                )
                for statistic in BOOTSTRAP_STATISTICS
            }
            for key in difference_draws
        },
        "note": (
            "Percentile bootstrap. Resample indices are drawn once and shared by every "
            "estimator, so the differences are PAIRED. An interval that excludes zero "
            "is reported as excluding zero; it is not called significant."
        ),
    }


def _difference(
    points: Mapping[str, Mapping[str, float | None]], first: str, second: str, statistic: str
) -> float | None:
    left = points.get(first, {}).get(statistic)
    right = points.get(second, {}).get(statistic)
    if left is None or right is None:
        return None
    return _round(left - right)


def _interval(
    statistic: str,
    point: float | None,
    draws: Sequence[float],
    samples: int,
    resamples: int,
    confidence: float,
) -> dict[str, Any]:
    if len(draws) < 2:
        low = high = None
    else:
        low, high = _percentiles(draws, confidence)
    return Interval(
        statistic=statistic,
        point=_round(point),
        low=_round(low),
        high=_round(high),
        samples=samples,
        resamples=resamples,
        confidence=confidence,
        higher_is_better=BOOTSTRAP_STATISTICS[statistic],
    ).to_dict()
