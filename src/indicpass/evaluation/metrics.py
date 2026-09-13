"""Classification, ranking and calibration metrics, from the standard library.

Nothing here is specific to passwords. Every function takes plain sequences of
labels or scores and returns a value or ``None`` -- never a substituted
number -- when the quantity is undefined for the input given. That mirrors the
convention :mod:`indicpass.password.validation` already uses for correlations:
an undefined statistic and a statistic that happens to be zero are different
findings, and returning ``0.0`` for both would report the second as the first.

Positive class and score direction
-----------------------------------
Every function here treats label ``1`` as the positive class. For this
project's usage that is "crackable within the stated budget" -- see
:mod:`indicpass.evaluation.budgets`. ``y_score`` must already be oriented so
that a **larger** value means **more likely positive**; nothing here inspects
which quantity it came from or flips it. IndicPass's own guess numbers run the
other way (a *smaller* guess number means a *weaker*, more attackable
password), so a caller scoring with them must negate first
(``-log10_guesses``). :func:`roc_auc` and :func:`pr_auc` are tested against
both a correctly- and an incorrectly-oriented score precisely so that mistake
cannot pass silently -- see ``tests/test_evaluation_metrics.py``.

Binary vs. multiclass
----------------------
The password evaluation this package supports is binary throughout
(crackable / not, at a stated attack budget), so :func:`confusion_matrix`,
:func:`precision`, :func:`recall`, :func:`f1`, :func:`mcc` and
:func:`balanced_accuracy` all default to that case, which has closed-form
definitions distinct from the multiclass ones. :func:`macro_f1` and
:func:`multiclass_confusion_matrix` generalise to more than two labels for
completeness -- section 4 of the evaluation brief asks for both -- and are
exercised in the test suite with synthetic labels; nothing in this project's
password data is evaluated as multiclass, and the report says so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "BinaryConfusion",
    "CalibrationResult",
    "ThresholdRow",
    "accuracy",
    "average_rank",
    "balanced_accuracy",
    "brier_score",
    "confusion_matrix",
    "expected_calibration_error",
    "f1",
    "macro_f1",
    "mcc",
    "multiclass_confusion_matrix",
    "pr_auc",
    "pr_points",
    "precision",
    "recall",
    "roc_auc",
    "roc_points",
    "threshold_sweep",
]


def _as_binary(values: Sequence[int]) -> list[int]:
    labels = {int(v) for v in values}
    if not labels <= {0, 1}:
        raise ValueError(f"Binary labels must be 0 or 1, got {sorted(labels)}.")
    return [int(v) for v in values]


# -- confusion matrix and the metrics built on it ----------------------------


@dataclass(frozen=True)
class BinaryConfusion:
    """Counts, plus support, for one binary classification at one threshold."""

    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def support(self) -> int:
        return self.tp + self.fp + self.tn + self.fn

    @property
    def positives(self) -> int:
        return self.tp + self.fn

    @property
    def negatives(self) -> int:
        return self.tn + self.fp

    def to_dict(self) -> dict[str, int]:
        return {"tp": self.tp, "fp": self.fp, "tn": self.tn, "fn": self.fn}


def confusion_matrix(y_true: Sequence[int], y_pred: Sequence[int]) -> BinaryConfusion:
    """Binary confusion matrix. Label ``1`` is positive.

    Raises on a length mismatch or a label outside ``{0, 1}`` rather than
    coercing -- a caller passing continuous scores here by mistake should see
    an exception, not a confusion matrix computed on nonsense.
    """
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true has {len(y_true)} entries, y_pred has {len(y_pred)}.")
    truth = _as_binary(y_true)
    pred = _as_binary(y_pred)
    tp = sum(1 for t, p in zip(truth, pred, strict=True) if t == 1 and p == 1)
    fp = sum(1 for t, p in zip(truth, pred, strict=True) if t == 0 and p == 1)
    tn = sum(1 for t, p in zip(truth, pred, strict=True) if t == 0 and p == 0)
    fn = sum(1 for t, p in zip(truth, pred, strict=True) if t == 1 and p == 0)
    return BinaryConfusion(tp=tp, fp=fp, tn=tn, fn=fn)


def accuracy(confusion: BinaryConfusion) -> float | None:
    """``None`` only when there is no support at all (an empty evaluation)."""
    if confusion.support == 0:
        return None
    return (confusion.tp + confusion.tn) / confusion.support


def precision(confusion: BinaryConfusion) -> float | None:
    """``None`` when the classifier predicted no positives -- undefined, not 0."""
    denominator = confusion.tp + confusion.fp
    return None if denominator == 0 else confusion.tp / denominator


def recall(confusion: BinaryConfusion) -> float | None:
    """``None`` when there are no actual positives to recall."""
    denominator = confusion.tp + confusion.fn
    return None if denominator == 0 else confusion.tp / denominator


def f1(confusion: BinaryConfusion) -> float | None:
    """Harmonic mean of :func:`precision` and :func:`recall`.

    ``None`` propagates: if either is undefined, so is F1. If both are defined
    but both zero, F1 is 0.0 by the standard convention (the harmonic mean's
    limit), not undefined.
    """
    p, r = precision(confusion), recall(confusion)
    if p is None or r is None:
        return None
    if p + r == 0:
        return 0.0
    return 2 * p * r / (p + r)


def balanced_accuracy(confusion: BinaryConfusion) -> float | None:
    """Mean of sensitivity (recall on 1) and specificity (recall on 0).

    ``None`` if either class has no actual members -- the usual case being a
    category or budget where every sample lands on one side of the ground
    truth, which makes "balance" meaningless rather than perfect.
    """
    sensitivity = recall(confusion)
    specificity = None if confusion.negatives == 0 else confusion.tn / confusion.negatives
    if sensitivity is None or specificity is None:
        return None
    return (sensitivity + specificity) / 2


def mcc(confusion: BinaryConfusion) -> float | None:
    """Matthews correlation coefficient. ``None`` when any marginal is zero.

    That happens whenever every sample shares one true label or the
    classifier predicted only one label -- the denominator is then zero by
    construction, and MCC is conventionally reported as undefined there
    rather than as 0, which would claim "no better than chance" about a case
    where chance was never measured.
    """
    tp, fp, tn, fn = confusion.tp, confusion.fp, confusion.tn, confusion.fn
    numerator = tp * tn - fp * fn
    denom_sq = (tp + fp) * (tp + fn) * (tn + fp) * (tn + fn)
    if denom_sq == 0:
        return None
    return numerator / math.sqrt(denom_sq)


# -- multiclass (generalises the above; not used on password data) ----------


def multiclass_confusion_matrix(
    y_true: Sequence[Any], y_pred: Sequence[Any], labels: Sequence[Any] | None = None
) -> dict[Any, dict[Any, int]]:
    """``matrix[true][pred] = count``, over every label seen (or *labels*)."""
    if len(y_true) != len(y_pred):
        raise ValueError(f"y_true has {len(y_true)} entries, y_pred has {len(y_pred)}.")
    ordered = list(labels) if labels is not None else sorted({*y_true, *y_pred}, key=str)
    matrix: dict[Any, dict[Any, int]] = {t: dict.fromkeys(ordered, 0) for t in ordered}
    for t, p in zip(y_true, y_pred, strict=True):
        matrix.setdefault(t, dict.fromkeys(ordered, 0))
        matrix[t][p] = matrix[t].get(p, 0) + 1
    return matrix


def macro_f1(
    y_true: Sequence[Any], y_pred: Sequence[Any], labels: Sequence[Any] | None = None
) -> dict[str, Any]:
    """Per-class one-vs-rest F1, unweighted-averaged. Works for binary too.

    Returns the per-class breakdown alongside the mean, because a macro
    average with one undefined class silently dropped is a different (and
    unlabelled) quantity from one computed over every class -- so the count
    of classes actually averaged is reported beside the value.
    """
    ordered = list(labels) if labels is not None else sorted({*y_true, *y_pred}, key=str)
    per_class: dict[Any, float | None] = {}
    for label in ordered:
        bin_true = [1 if t == label else 0 for t in y_true]
        bin_pred = [1 if p == label else 0 for p in y_pred]
        per_class[label] = f1(confusion_matrix(bin_true, bin_pred))
    defined = [v for v in per_class.values() if v is not None]
    return {
        "per_class": per_class,
        "macro_f1": (sum(defined) / len(defined)) if defined else None,
        "classes_averaged": len(defined),
        "classes_total": len(ordered),
    }


# -- ranking: ROC-AUC and PR-AUC ---------------------------------------------


def average_rank(values: Sequence[float]) -> list[float]:
    """1-based ranks, ascending, with ties given the average of their ranks."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        shared = (i + j) / 2 + 1
        for k in order[i : j + 1]:
            ranks[k] = shared
        i = j + 1
    return ranks


def roc_points(y_true: Sequence[int], y_score: Sequence[float]) -> list[tuple[float, float]]:
    """``(fpr, tpr)`` pairs tracing the ROC curve, from ``(0, 0)`` to ``(1, 1)``.

    Scores are consumed **descending**, and tied scores are resolved together
    (one point per distinct score, not per sample) -- otherwise two passwords
    an estimator scored identically would be drawn as if one were riskier,
    which is evidence the estimator never provided.
    """
    if len(y_true) != len(y_score):
        raise ValueError(f"y_true has {len(y_true)} entries, y_score has {len(y_score)}.")
    truth = _as_binary(y_true)
    total_pos = sum(truth)
    total_neg = len(truth) - total_pos
    if total_pos == 0 or total_neg == 0:
        return []

    order = sorted(range(len(truth)), key=lambda i: y_score[i], reverse=True)
    points = [(0.0, 0.0)]
    tp = fp = 0
    i = 0
    while i < len(order):
        j = i
        score = y_score[order[i]]
        while j < len(order) and y_score[order[j]] == score:
            if truth[order[j]] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        points.append((fp / total_neg, tp / total_pos))
        i = j
    return points


def roc_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float | None:
    """Area under the ROC curve, via the rank-sum (Mann-Whitney U) identity.

    Equivalent to trapezoidal integration of :func:`roc_points` but computed
    directly from tie-averaged ranks, which is exact under ties rather than an
    approximation of the stepped curve. ``None`` when one class is absent --
    the curve is then undefined, not perfect.
    """
    truth = _as_binary(y_true)
    if len(truth) != len(y_score):
        raise ValueError(f"y_true has {len(truth)} entries, y_score has {len(y_score)}.")
    n_pos = sum(truth)
    n_neg = len(truth) - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    ranks = average_rank(list(y_score))
    rank_sum_pos = sum(r for r, t in zip(ranks, truth, strict=True) if t == 1)
    return (rank_sum_pos - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def pr_points(y_true: Sequence[int], y_score: Sequence[float]) -> list[tuple[float, float]]:
    """``(recall, precision)`` pairs, scores consumed descending, ties grouped."""
    if len(y_true) != len(y_score):
        raise ValueError(f"y_true has {len(y_true)} entries, y_score has {len(y_score)}.")
    truth = _as_binary(y_true)
    total_pos = sum(truth)
    if total_pos == 0:
        return []

    order = sorted(range(len(truth)), key=lambda i: y_score[i], reverse=True)
    points: list[tuple[float, float]] = []
    tp = fp = 0
    i = 0
    while i < len(order):
        j = i
        score = y_score[order[i]]
        while j < len(order) and y_score[order[j]] == score:
            if truth[order[j]] == 1:
                tp += 1
            else:
                fp += 1
            j += 1
        recall_value = tp / total_pos
        precision_value = tp / (tp + fp) if (tp + fp) else 1.0
        points.append((recall_value, precision_value))
        i = j
    return points


def pr_auc(y_true: Sequence[int], y_score: Sequence[float]) -> float | None:
    """Average precision: :math:`\\sum (R_n - R_{n-1}) \\cdot P_n` over the PR curve.

    Not trapezoidal interpolation between precision points, which is known to
    be optimistic on a PR curve (precision is not concave the way ROC's TPR
    is). This is the definition used by every standard implementation of
    "average precision". ``None`` when there are no positives -- recall is
    then undefined everywhere, not the curve's area being zero.
    """
    points = pr_points(y_true, y_score)
    if not points:
        return None
    area = 0.0
    prev_recall = 0.0
    for recall_value, precision_value in points:
        area += (recall_value - prev_recall) * precision_value
        prev_recall = recall_value
    return area


# -- threshold sweep ----------------------------------------------------------


@dataclass(frozen=True)
class ThresholdRow:
    threshold: float
    confusion: BinaryConfusion
    precision: float | None
    recall: float | None
    f1: float | None
    accuracy: float | None
    balanced_accuracy: float | None
    mcc: float | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold,
            **self.confusion.to_dict(),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
            "accuracy": self.accuracy,
            "balanced_accuracy": self.balanced_accuracy,
            "mcc": self.mcc,
        }


def threshold_sweep(
    y_true: Sequence[int], y_score: Sequence[float], thresholds: Sequence[float]
) -> list[ThresholdRow]:
    """Every classification metric, at every threshold in *thresholds*.

    Predicted positive iff ``score >= threshold``, consistent with the module
    docstring's direction convention. This is a diagnostic sweep, not a
    threshold *selection* -- see ``docs/evaluation.md`` section 6 for why no
    single value here is picked as "the" operating point for this project's
    frozen benchmark, which has no held-out development split.
    """
    truth = _as_binary(y_true)
    if len(truth) != len(y_score):
        raise ValueError(f"y_true has {len(truth)} entries, y_score has {len(y_score)}.")
    rows: list[ThresholdRow] = []
    for threshold in thresholds:
        predicted = [1 if s >= threshold else 0 for s in y_score]
        confusion = confusion_matrix(truth, predicted)
        rows.append(
            ThresholdRow(
                threshold=threshold,
                confusion=confusion,
                precision=precision(confusion),
                recall=recall(confusion),
                f1=f1(confusion),
                accuracy=accuracy(confusion),
                balanced_accuracy=balanced_accuracy(confusion),
                mcc=mcc(confusion),
            )
        )
    return rows


# -- calibration (probabilities only -- see the module docstring) -----------


def brier_score(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    """Mean squared error between a genuine probability and the outcome.

    Raises if *y_prob* is not in ``[0, 1]``: this project's guess numbers are
    not probabilities, and the caller must not pass a normalised strength
    score here and call the result a Brier score. See
    ``docs/evaluation.md`` section 7.
    """
    truth = _as_binary(y_true)
    if len(truth) != len(y_prob):
        raise ValueError(f"y_true has {len(truth)} entries, y_prob has {len(y_prob)}.")
    for p in y_prob:
        if not 0.0 <= p <= 1.0:
            raise ValueError(
                f"brier_score requires probabilities in [0, 1]; got {p}. This is not a "
                "generic distance function -- see the module docstring."
            )
    return sum((p - t) ** 2 for p, t in zip(y_prob, truth, strict=True)) / len(truth)


@dataclass(frozen=True)
class CalibrationResult:
    ece: float
    bins: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {"ece": self.ece, "bins": list(self.bins)}


def expected_calibration_error(
    y_true: Sequence[int], y_prob: Sequence[float], *, n_bins: int = 10
) -> CalibrationResult:
    """Fixed equal-width bins over ``[0, 1]``, population-weighted mean gap.

    ``ECE = sum_b (n_b / n) * |accuracy_b - confidence_b|``. Same probability
    guard as :func:`brier_score`. Empty bins are omitted from the bin list but
    do not contribute to the weighted sum, so ``n_bins`` choices with no data
    at the extremes do not bias the estimate.
    """
    truth = _as_binary(y_true)
    if len(truth) != len(y_prob):
        raise ValueError(f"y_true has {len(truth)} entries, y_prob has {len(y_prob)}.")
    for p in y_prob:
        if not 0.0 <= p <= 1.0:
            raise ValueError(
                f"expected_calibration_error requires probabilities in [0, 1]; got {p}."
            )
    if n_bins < 1:
        raise ValueError(f"n_bins must be >= 1, got {n_bins}.")

    edges = [i / n_bins for i in range(n_bins + 1)]
    buckets: list[list[tuple[float, int]]] = [[] for _ in range(n_bins)]
    for p, t in zip(y_prob, truth, strict=True):
        index = min(n_bins - 1, int(p * n_bins))
        buckets[index].append((p, t))

    total = len(truth)
    weighted_gap = 0.0
    bins: list[dict[str, Any]] = []
    for index, bucket in enumerate(buckets):
        if not bucket:
            continue
        confidence = sum(p for p, _ in bucket) / len(bucket)
        observed = sum(t for _, t in bucket) / len(bucket)
        weighted_gap += (len(bucket) / total) * abs(observed - confidence)
        bins.append(
            {
                "bin": index,
                "low": edges[index],
                "high": edges[index + 1],
                "count": len(bucket),
                "mean_confidence": round(confidence, 6),
                "mean_observed": round(observed, 6),
            }
        )
    return CalibrationResult(ece=round(weighted_gap, 6), bins=tuple(bins))
