"""Paired percentile bootstrap for classification and ranking statistics.

Same resampling scheme as :func:`indicpass.password.uncertainty.bootstrap_group`
(percentile bootstrap, indices drawn once per resample and shared across every
estimator so paired differences are actually paired) applied to a different
family of statistics: accuracy, precision, recall, F1, balanced accuracy, MCC
at a fixed threshold, plus ROC-AUC and PR-AUC. That module's statistics are
all functions of a *(predicted, observed)* error; these are functions of
*(y_true, y_score)*, so this is a second, self-contained implementation of the
resampling loop rather than a reused one -- but the same rules apply:
resample indices are shared across estimators, an interval below
``min_samples`` is not computed, and an interval excluding zero is reported as
exactly that, never as "significant".
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from indicpass.evaluation.metrics import (
    accuracy,
    balanced_accuracy,
    confusion_matrix,
    f1,
    mcc,
    pr_auc,
    precision,
    recall,
    roc_auc,
)

__all__ = [
    "CLASSIFICATION_STATISTICS",
    "bootstrap_classification",
    "compute_classification_statistics",
]

#: Statistic name -> whether larger is better. ROC-AUC and PR-AUC are
#: threshold-independent and computed alongside the threshold-dependent ones
#: so a single resample scores everything in one pass.
CLASSIFICATION_STATISTICS: Mapping[str, bool] = {
    "accuracy": True,
    "precision": True,
    "recall": True,
    "f1": True,
    "balanced_accuracy": True,
    "mcc": True,
    "roc_auc": True,
    "pr_auc": True,
}


def compute_classification_statistics(
    y_true: Sequence[int], y_score: Sequence[float], *, threshold: float
) -> dict[str, float | None]:
    """Every statistic in :data:`CLASSIFICATION_STATISTICS`, on one sample.

    Predicted positive iff ``score >= threshold``, matching
    :func:`indicpass.evaluation.metrics.threshold_sweep`'s convention.
    """
    predicted = [1 if s >= threshold else 0 for s in y_score]
    confusion = confusion_matrix(y_true, predicted)
    return {
        "accuracy": accuracy(confusion),
        "precision": precision(confusion),
        "recall": recall(confusion),
        "f1": f1(confusion),
        "balanced_accuracy": balanced_accuracy(confusion),
        "mcc": mcc(confusion),
        "roc_auc": roc_auc(y_true, y_score),
        "pr_auc": pr_auc(y_true, y_score),
    }


@dataclass(frozen=True)
class _Interval:
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
            "point": _round(self.point),
            "ci_low": _round(self.low),
            "ci_high": _round(self.high),
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


def _percentiles(values: Sequence[float], confidence: float) -> tuple[float, float]:
    ordered = sorted(values)
    tail = (1.0 - confidence) / 2.0
    n = len(ordered)
    low = ordered[min(n - 1, max(0, math.floor(tail * n)))]
    high = ordered[min(n - 1, max(0, math.ceil((1.0 - tail) * n) - 1))]
    return low, high


def bootstrap_classification(
    y_true: Sequence[int],
    scores: Mapping[str, Sequence[float]],
    *,
    threshold: float,
    pairs: Sequence[tuple[str, str]] = (),
    seed: int = 42,
    resamples: int = 2000,
    confidence: float = 0.95,
    min_samples: int = 20,
    label: str = "",
) -> dict[str, Any]:
    """Confidence intervals for every estimator in *scores*, and named pairs.

    *threshold* fixes the classification cut for every resample -- it is not
    re-derived per resample, which would let sampling noise pick a different
    operating point for every draw and answer a different question than "how
    uncertain is this classifier's performance at this threshold".
    """
    count = len(y_true)
    for name, values in scores.items():
        if len(values) != count:
            raise ValueError(f"Estimator {name!r} has {len(values)} scores for {count} labels.")

    points = {
        name: compute_classification_statistics(y_true, values, threshold=threshold)
        for name, values in scores.items()
    }

    if count < min_samples or resamples <= 0:
        return {
            "samples": count,
            "resamples": 0,
            "confidence": confidence,
            "threshold": threshold,
            "below_minimum": count < min_samples,
            "minimum_samples": min_samples,
            "estimators": {
                name: {
                    statistic: _Interval(
                        statistic, _round(values[statistic]), None, None, count, 0,
                        confidence, CLASSIFICATION_STATISTICS[statistic],
                    ).to_dict()
                    for statistic in CLASSIFICATION_STATISTICS
                }
                for name, values in points.items()
            },
            "differences": {
                f"{a}-minus-{b}": {
                    statistic: _Interval(
                        statistic, _difference(points, a, b, statistic), None, None, count, 0,
                        confidence, CLASSIFICATION_STATISTICS[statistic],
                    ).to_dict()
                    for statistic in CLASSIFICATION_STATISTICS
                }
                for a, b in pairs
                if a in points and b in points
            },
            "note": (
                f"Fewer than {min_samples} labelled targets: point estimates only. An "
                "interval over a population this small would be wider than the quantity "
                "it describes."
            ),
        }

    rng = random.Random(f"eval-bootstrap:{seed}:{label}:{threshold}")
    draws: dict[str, dict[str, list[float]]] = {
        name: {statistic: [] for statistic in CLASSIFICATION_STATISTICS} for name in scores
    }
    diff_keys = [f"{a}-minus-{b}" for a, b in pairs if a in scores and b in scores]
    diff_draws: dict[str, dict[str, list[float]]] = {
        key: {statistic: [] for statistic in CLASSIFICATION_STATISTICS} for key in diff_keys
    }

    for _ in range(resamples):
        indices = [rng.randrange(count) for _ in range(count)]
        resampled_truth = [y_true[i] for i in indices]
        scored: dict[str, dict[str, float | None]] = {}
        for name, values in scores.items():
            scored[name] = compute_classification_statistics(
                resampled_truth, [values[i] for i in indices], threshold=threshold
            )
            for statistic, value in scored[name].items():
                if value is not None:
                    draws[name][statistic].append(value)
        for key in diff_keys:
            first, second = key.split("-minus-")
            for statistic in CLASSIFICATION_STATISTICS:
                left, right = scored[first][statistic], scored[second][statistic]
                if left is not None and right is not None:
                    diff_draws[key][statistic].append(left - right)

    return {
        "samples": count,
        "resamples": resamples,
        "confidence": confidence,
        "threshold": threshold,
        "below_minimum": False,
        "minimum_samples": min_samples,
        "estimators": {
            name: {
                statistic: _interval(
                    statistic, points[name][statistic], draws[name][statistic],
                    count, resamples, confidence,
                )
                for statistic in CLASSIFICATION_STATISTICS
            }
            for name in scores
        },
        "differences": {
            key: {
                statistic: _interval(
                    statistic,
                    _difference(points, *key.split("-minus-"), statistic),
                    diff_draws[key][statistic],
                    count, resamples, confidence,
                )
                for statistic in CLASSIFICATION_STATISTICS
            }
            for key in diff_keys
        },
        "note": (
            "Percentile bootstrap, resample indices shared across estimators so "
            "differences are PAIRED. An interval excluding zero is reported as "
            "excluding zero; it is not called significant."
        ),
    }


def _difference(
    points: Mapping[str, Mapping[str, float | None]], first: str, second: str, statistic: str
) -> float | None:
    left = points.get(first, {}).get(statistic)
    right = points.get(second, {}).get(statistic)
    return None if left is None or right is None else left - right


def _interval(
    statistic: str, point: float | None, draws: Sequence[float],
    samples: int, resamples: int, confidence: float,
) -> dict[str, Any]:
    low = high = None
    if len(draws) >= 2:
        low, high = _percentiles(draws, confidence)
    return _Interval(
        statistic, point, low, high, samples, resamples, confidence,
        CLASSIFICATION_STATISTICS[statistic],
    ).to_dict()
