"""Unit tests for indicpass.evaluation.bootstrap."""

from __future__ import annotations

import pytest

from indicpass.evaluation.bootstrap import (
    bootstrap_classification,
    compute_classification_statistics,
)
from indicpass.evaluation.metrics import accuracy, confusion_matrix, roc_auc


def test_compute_classification_statistics_matches_direct_metrics():
    y_true = [0, 0, 1, 1, 1]
    y_score = [0.1, 0.6, 0.4, 0.7, 0.9]
    stats = compute_classification_statistics(y_true, y_score, threshold=0.5)
    predicted = [1 if s >= 0.5 else 0 for s in y_score]
    assert stats["accuracy"] == accuracy(confusion_matrix(y_true, predicted))
    assert stats["roc_auc"] == roc_auc(y_true, y_score)


def test_bootstrap_below_minimum_reports_point_estimates_only():
    y_true = [0, 1, 0, 1]
    scores = {"a": [0.2, 0.8, 0.3, 0.9], "b": [0.4, 0.6, 0.4, 0.6]}
    result = bootstrap_classification(
        y_true, scores, threshold=0.5, pairs=[("a", "b")], min_samples=20
    )
    assert result["below_minimum"] is True
    assert result["resamples"] == 0
    for statistic in ("accuracy", "f1", "roc_auc"):
        entry = result["estimators"]["a"][statistic]
        assert entry["ci_low"] is None and entry["ci_high"] is None
        assert entry["point"] is not None or statistic == "roc_auc"


def test_bootstrap_difference_point_matches_component_difference():
    y_true = [0, 1] * 15
    scores = {
        "a": [0.9 if t else 0.1 for t in y_true],  # perfect
        "b": [0.5 for _ in y_true],  # uninformative
    }
    result = bootstrap_classification(
        y_true, scores, threshold=0.5, pairs=[("a", "b")], resamples=50, min_samples=5, seed=1
    )
    diff = result["differences"]["a-minus-b"]["accuracy"]["point"]
    a_point = result["estimators"]["a"]["accuracy"]["point"]
    b_point = result["estimators"]["b"]["accuracy"]["point"]
    assert diff == pytest.approx(a_point - b_point)


def test_bootstrap_is_deterministic_given_the_same_seed():
    y_true = [0, 1, 0, 1, 1, 0, 1, 0, 1, 0, 1, 1, 0, 0, 1, 0, 1, 0, 1, 1, 0, 1, 0, 1, 1]
    scores = {"a": [0.9 if t else 0.1 for t in y_true]}
    kwargs = {"threshold": 0.5, "resamples": 200, "min_samples": 5, "seed": 7}
    first = bootstrap_classification(y_true, scores, **kwargs)
    second = bootstrap_classification(y_true, scores, **kwargs)
    assert first == second


def test_bootstrap_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        bootstrap_classification([0, 1], {"a": [0.1]}, threshold=0.5)


def test_bootstrap_pairs_missing_estimator_are_skipped():
    y_true = [0, 1] * 15
    scores = {"a": [0.9 if t else 0.1 for t in y_true]}
    result = bootstrap_classification(
        y_true, scores, threshold=0.5, pairs=[("a", "does-not-exist")], resamples=20, min_samples=5
    )
    assert result["differences"] == {}
