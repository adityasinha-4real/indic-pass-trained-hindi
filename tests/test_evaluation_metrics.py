"""Unit tests for indicpass.evaluation.metrics.

Two of the ranking examples (roc_auc, pr_auc) are the canonical y_true /
y_score pairs from scikit-learn's own docstrings, with the values it
documents for them -- not because this project depends on scikit-learn, but
because they are independently-known-correct answers to check a from-scratch
implementation against.
"""

from __future__ import annotations

import math

import pytest

from indicpass.evaluation.metrics import (
    accuracy,
    balanced_accuracy,
    brier_score,
    confusion_matrix,
    expected_calibration_error,
    f1,
    macro_f1,
    mcc,
    multiclass_confusion_matrix,
    pr_auc,
    precision,
    recall,
    roc_auc,
    threshold_sweep,
)

# tp=5, fp=2, tn=3, fn=1
Y_TRUE = [1, 1, 1, 1, 1, 1, 0, 0, 0, 0, 0]
Y_PRED = [1, 1, 1, 1, 1, 0, 1, 1, 0, 0, 0]


def test_confusion_matrix_counts():
    c = confusion_matrix(Y_TRUE, Y_PRED)
    assert (c.tp, c.fp, c.tn, c.fn) == (5, 2, 3, 1)
    assert c.support == 11
    assert c.positives == 6
    assert c.negatives == 5


def test_confusion_matrix_rejects_mismatched_length():
    with pytest.raises(ValueError):
        confusion_matrix([1, 0], [1])


def test_confusion_matrix_rejects_non_binary_labels():
    with pytest.raises(ValueError):
        confusion_matrix([0, 1, 2], [0, 1, 1])


def test_accuracy_precision_recall_f1():
    c = confusion_matrix(Y_TRUE, Y_PRED)
    assert accuracy(c) == pytest.approx(8 / 11)
    assert precision(c) == pytest.approx(5 / 7)
    assert recall(c) == pytest.approx(5 / 6)
    p, r = precision(c), recall(c)
    assert f1(c) == pytest.approx(2 * p * r / (p + r))


def test_balanced_accuracy_and_mcc():
    c = confusion_matrix(Y_TRUE, Y_PRED)
    assert balanced_accuracy(c) == pytest.approx((5 / 6 + 3 / 5) / 2)
    numerator = 5 * 3 - 2 * 1
    denom = math.sqrt(7 * 6 * 5 * 4)
    assert mcc(c) == pytest.approx(numerator / denom)


def test_undefined_metrics_are_none_not_zero():
    """Zero-division handling is deterministic: undefined, not a fabricated 0."""
    # No predicted positives at all -> precision undefined.
    c = confusion_matrix([1, 0, 1], [0, 0, 0])
    assert precision(c) is None
    assert f1(c) is None
    # No actual positives at all -> recall, balanced_accuracy undefined.
    c2 = confusion_matrix([0, 0, 0], [0, 1, 0])
    assert recall(c2) is None
    assert balanced_accuracy(c2) is None
    # A zero marginal makes MCC's denominator zero.
    c3 = confusion_matrix([0, 0, 0, 0], [0, 0, 0, 0])
    assert mcc(c3) is None
    # Empty evaluation -> accuracy undefined.
    empty = confusion_matrix([], [])
    assert accuracy(empty) is None


def test_f1_is_zero_when_both_precision_and_recall_are_zero_but_defined():
    c = confusion_matrix([1, 0], [0, 1])  # tp=0, fp=1, fn=1, tn=0
    assert precision(c) == 0.0
    assert recall(c) == 0.0
    assert f1(c) == 0.0


def test_macro_f1_binary_matches_average_of_both_classes():
    result = macro_f1(Y_TRUE, Y_PRED, labels=[0, 1])
    c = confusion_matrix(Y_TRUE, Y_PRED)
    f1_pos = f1(c)
    f1_neg = f1(confusion_matrix([1 - t for t in Y_TRUE], [1 - p for p in Y_PRED]))
    assert result["macro_f1"] == pytest.approx((f1_pos + f1_neg) / 2)
    assert result["classes_averaged"] == 2


def test_macro_f1_three_class():
    y_true = ["a", "a", "b", "b", "c", "c"]
    y_pred = ["a", "b", "b", "b", "c", "a"]
    result = macro_f1(y_true, y_pred)
    # a: tp=1 fp=1(c->a) fn=1(a->b) -> P=.5 R=.5 F1=.5
    # b: tp=2 fp=1(a->b) fn=0        -> P=2/3 R=1 F1=.8
    # c: tp=1 fp=0 fn=1(c->a)        -> P=1 R=.5 F1=2/3
    assert result["per_class"]["a"] == pytest.approx(0.5)
    assert result["per_class"]["b"] == pytest.approx(0.8)
    assert result["per_class"]["c"] == pytest.approx(2 / 3)
    assert result["macro_f1"] == pytest.approx((0.5 + 0.8 + 2 / 3) / 3)


def test_multiclass_confusion_matrix():
    matrix = multiclass_confusion_matrix(["a", "a", "b"], ["a", "b", "b"], labels=["a", "b"])
    assert matrix == {"a": {"a": 1, "b": 1}, "b": {"a": 0, "b": 1}}


# -- ranking ------------------------------------------------------------

SKLEARN_Y_TRUE = [0, 0, 1, 1]
SKLEARN_Y_SCORE = [0.1, 0.4, 0.35, 0.8]


def test_roc_auc_matches_known_value():
    assert roc_auc(SKLEARN_Y_TRUE, SKLEARN_Y_SCORE) == pytest.approx(0.75)


def test_pr_auc_matches_known_value():
    assert pr_auc(SKLEARN_Y_TRUE, SKLEARN_Y_SCORE) == pytest.approx(0.8333333333333333)


def test_roc_auc_perfect_separation_is_one():
    assert roc_auc([0, 0, 1, 1], [0.1, 0.2, 0.9, 0.8]) == pytest.approx(1.0)


def test_roc_auc_score_direction_matters():
    """Flipping the score's sign must complement the AUC -- proves direction
    is not silently ignored by the rank-based computation."""
    y_true = [0, 0, 1, 1]
    y_score = [0.1, 0.4, 0.35, 0.8]
    forward = roc_auc(y_true, y_score)
    backward = roc_auc(y_true, [-s for s in y_score])
    assert forward == pytest.approx(0.75)
    assert backward == pytest.approx(1 - 0.75)


def test_roc_auc_and_pr_auc_undefined_with_one_class():
    assert roc_auc([1, 1, 1], [0.1, 0.2, 0.3]) is None
    assert pr_auc([0, 0, 0], [0.1, 0.2, 0.3]) is None


def test_roc_auc_rejects_length_mismatch():
    with pytest.raises(ValueError):
        roc_auc([1, 0], [0.1, 0.2, 0.3])


# -- threshold sweep ------------------------------------------------------


def test_threshold_sweep_shape_and_monotonic_recall():
    y_true = [0, 0, 1, 1, 1]
    y_score = [0.1, 0.3, 0.4, 0.6, 0.9]
    rows = threshold_sweep(y_true, y_score, [0.0, 0.35, 0.5, 0.95])
    assert [row.threshold for row in rows] == [0.0, 0.35, 0.5, 0.95]
    # Recall (predicted positive iff score >= threshold) is non-increasing as
    # the threshold rises.
    recalls = [row.recall for row in rows]
    assert recalls == sorted(recalls, reverse=True)
    # At the lowest threshold, everything is predicted positive.
    assert rows[0].confusion.to_dict()["fn"] == 0
    # At the highest threshold, nothing clears it.
    assert rows[-1].confusion.to_dict() == {"tp": 0, "fp": 0, "tn": 2, "fn": 3}


def test_threshold_sweep_is_deterministic():
    y_true = [0, 1, 0, 1, 1]
    y_score = [0.2, 0.7, 0.4, 0.6, 0.9]
    first = [row.to_dict() for row in threshold_sweep(y_true, y_score, [0.5])]
    second = [row.to_dict() for row in threshold_sweep(y_true, y_score, [0.5])]
    assert first == second


# -- calibration (probabilities only) ------------------------------------


def test_brier_score_known_value():
    # Perfect predictions -> 0. Completely wrong (confident, wrong) -> 1.
    assert brier_score([1, 0], [1.0, 0.0]) == pytest.approx(0.0)
    assert brier_score([1, 0], [0.0, 1.0]) == pytest.approx(1.0)
    assert brier_score([1, 0], [0.5, 0.5]) == pytest.approx(0.25)


def test_brier_score_rejects_non_probabilities():
    with pytest.raises(ValueError):
        brier_score([1, 0], [1.5, 0.5])


def test_expected_calibration_error_perfect_calibration_is_zero():
    # Two bins, confidence == observed frequency within each: 1/5 positives at
    # confidence 0.2, 4/5 positives at confidence 0.8.
    y_true = [1, 0, 0, 0, 0, 1, 1, 1, 1, 0]
    y_prob = [0.2] * 5 + [0.8] * 5
    result = expected_calibration_error(y_true, y_prob, n_bins=10)
    assert result.ece == pytest.approx(0.0)


def test_expected_calibration_error_detects_miscalibration():
    # Always says 0.9 confident, but only right half the time.
    y_true = [1, 0, 1, 0]
    y_prob = [0.9, 0.9, 0.9, 0.9]
    result = expected_calibration_error(y_true, y_prob, n_bins=10)
    assert result.ece == pytest.approx(0.4)  # |0.5 observed - 0.9 confidence|


def test_expected_calibration_error_rejects_non_probabilities():
    with pytest.raises(ValueError):
        expected_calibration_error([1, 0], [2.0, -1.0])
