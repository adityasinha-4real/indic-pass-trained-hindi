"""Unit tests for indicpass.evaluation.budgets."""

from __future__ import annotations

import math

import pytest

from indicpass.evaluation.budgets import (
    attack_budget_table,
    crackable_within_budget,
    guess_number_stats,
    percentile,
)


def test_crackable_within_budget():
    assert crackable_within_budget(True, 100, 1000.0) is True
    assert crackable_within_budget(True, 10_000, 1000.0) is False
    # Uncovered is never crackable, whatever the rank field happens to hold.
    assert crackable_within_budget(False, 1, 1000.0) is False
    assert crackable_within_budget(True, None, 1000.0) is False


def test_attack_budget_table_counts_uncovered_as_not_cracked():
    covered = [True, True, False, True]
    ranks = [10, 10_000, None, 500]
    rows = attack_budget_table(covered, ranks, budgets=[100.0, 1000.0, 100000.0])
    by_budget = {row["budget"]: row for row in rows}
    # Only rank=10 is <= 100.
    assert by_budget[100.0]["count"] == 1
    assert by_budget[100.0]["total"] == 4
    assert by_budget[100.0]["success_rate"] == pytest.approx(0.25)
    # rank=10 and rank=500 are <= 1000.
    assert by_budget[1000.0]["count"] == 2
    # All three covered ranks are <= 100000; the uncovered one still never counts.
    assert by_budget[100000.0]["count"] == 3
    assert by_budget[100000.0]["success_rate"] == pytest.approx(0.75)


def test_attack_budget_table_rejects_length_mismatch():
    with pytest.raises(ValueError):
        attack_budget_table([True], [1, 2])


def test_attack_budget_table_empty_population():
    rows = attack_budget_table([], [])
    assert all(row["total"] == 0 and row["success_rate"] is None for row in rows)


def test_percentile_known_values():
    values = [1.0, 2.0, 3.0, 4.0]
    assert percentile(values, 0.0) == 1.0
    assert percentile(values, 1.0) == 4.0
    assert percentile(values, 0.5) == pytest.approx(2.5)


def test_percentile_single_value():
    assert percentile([7.0], 0.3) == 7.0


def test_percentile_rejects_bad_q():
    with pytest.raises(ValueError):
        percentile([1.0, 2.0], 1.5)
    with pytest.raises(ValueError):
        percentile([], 0.5)


def test_guess_number_stats_known_values():
    # log10 values 1, 2, 3, 4, 5 -> geometric mean log10 is their arithmetic
    # mean, 3.0; median is 3.0.
    stats = guess_number_stats([1.0, 2.0, 3.0, 4.0, 5.0], source="estimated")
    assert stats.source == "estimated"
    assert stats.samples == 5
    assert stats.median_log10 == pytest.approx(3.0)
    assert stats.geometric_mean_log10 == pytest.approx(3.0)
    assert stats.median == pytest.approx(1000.0)
    assert stats.geometric_mean == pytest.approx(1000.0)
    assert stats.quantiles_log10["p50"] == pytest.approx(3.0)


def test_guess_number_stats_excludes_non_finite():
    stats = guess_number_stats([1.0, math.inf, 2.0, math.nan], source="observed")
    assert stats.samples == 2
    assert stats.excluded_non_finite == 2
    assert stats.median_log10 == pytest.approx(1.5)


def test_guess_number_stats_empty_after_exclusion():
    stats = guess_number_stats([math.inf, math.nan], source="observed")
    assert stats.samples == 0
    assert stats.median_log10 is None
    assert stats.geometric_mean is None
    assert set(stats.quantiles_log10.values()) == {None}


def test_guess_number_stats_rejects_unknown_source():
    with pytest.raises(ValueError):
        guess_number_stats([1.0], source="guessed")


def test_guess_number_stats_never_mixes_estimated_and_observed_labels():
    estimated = guess_number_stats([1.0, 2.0], source="estimated")
    observed = guess_number_stats([1.0, 2.0], source="observed")
    assert estimated.to_dict()["source"] == "estimated"
    assert observed.to_dict()["source"] == "observed"
    assert "estimated" in estimated.to_dict()["note"]
    assert "observed" in observed.to_dict()["note"]
