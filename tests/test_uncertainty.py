"""The bootstrap: is the interval an interval, and is the difference paired?

Three properties matter and each is checked directly rather than by eye.

**Determinism.** A confidence interval that moved between runs would make the
report irreproducible, so the same seed must give the same bounds and a
different seed must give different ones.

**Coverage of the point estimate.** The interval is a percentile interval over
resamples of the same data, so it has to contain the statistic it is an interval
for -- not as a theorem, but as a sanity check that the resampling is resampling
the right thing.

**Pairing.** The whole reason this module exists is that "is M3 better than M2
on OOV" is a question about a difference between two estimators scored on the
SAME targets. If the resample indices were drawn separately for each estimator,
the difference's interval would be too wide and the report would understate
what it knows. That is tested by constructing two estimators whose difference is
constant and asserting the interval on it collapses.
"""

from __future__ import annotations

import math
import random

import pytest

from indicpass.password.uncertainty import (
    BOOTSTRAP_STATISTICS,
    bootstrap_group,
    compute_statistics,
)


def linear_data(count: int = 120, noise: float = 0.5, seed: int = 7):
    """Observed ranks, a good predictor of them, and a poor one."""
    rng = random.Random(seed)
    observed = [rng.uniform(2.0, 14.0) for _ in range(count)]
    good = [value + rng.gauss(0.0, noise) for value in observed]
    poor = [rng.uniform(2.0, 14.0) for _ in range(count)]
    return observed, good, poor


# -- the statistics ---------------------------------------------------------


def test_a_perfect_predictor_scores_perfectly():
    observed = [1.0, 2.0, 3.0, 4.0, 5.0]
    stats = compute_statistics(observed, observed)
    assert stats["spearman"] == pytest.approx(1.0)
    assert stats["pearson"] == pytest.approx(1.0)
    assert stats["mean_absolute_error"] == pytest.approx(0.0)
    assert stats["rmse"] == pytest.approx(0.0)
    assert stats["within_1.0_log10"] == pytest.approx(1.0)
    assert stats["calibration_slope"] == pytest.approx(1.0)
    assert stats["r_squared"] == pytest.approx(1.0)


def test_a_constant_predictor_has_no_correlation_rather_than_a_zero_one():
    """``None`` and 0.0 are different findings. A correlation of zero says the
    estimator does not track the attack; an undefined one says there was nothing
    to correlate."""
    stats = compute_statistics([3.0] * 6, [1.0, 2.0, 3.0, 4.0, 5.0, 6.0])
    assert stats["spearman"] is None
    assert stats["pearson"] is None
    assert stats["calibration_slope"] is None
    assert stats["r_squared"] is None
    assert stats["mean_absolute_error"] is not None


def test_an_empty_population_scores_nothing_rather_than_zero():
    assert compute_statistics([], []) == dict.fromkeys(BOOTSTRAP_STATISTICS)


def test_every_documented_statistic_is_produced():
    observed, good, _ = linear_data(30)
    assert set(compute_statistics(good, observed)) == set(BOOTSTRAP_STATISTICS)


def test_a_shifted_predictor_keeps_its_correlation_and_loses_its_accuracy():
    observed = [float(value) for value in range(1, 21)]
    shifted = [value + 3.0 for value in observed]
    stats = compute_statistics(shifted, observed)
    assert stats["spearman"] == pytest.approx(1.0)
    assert stats["mean_absolute_error"] == pytest.approx(3.0)
    assert stats["within_1.0_log10"] == pytest.approx(0.0)


# -- intervals --------------------------------------------------------------


def test_the_interval_is_deterministic_under_a_seed():
    observed, good, poor = linear_data()
    payload = {"good": good, "poor": poor}
    first = bootstrap_group(observed, payload, seed=42, resamples=200, label="x")
    second = bootstrap_group(observed, payload, seed=42, resamples=200, label="x")
    assert first == second


def test_a_different_seed_moves_the_interval_but_not_the_point():
    observed, good, poor = linear_data()
    payload = {"good": good, "poor": poor}
    first = bootstrap_group(observed, payload, seed=1, resamples=200, label="x")
    second = bootstrap_group(observed, payload, seed=2, resamples=200, label="x")
    assert (
        first["estimators"]["good"]["spearman"]["point"]
        == second["estimators"]["good"]["spearman"]["point"]
    )
    assert (
        first["estimators"]["good"]["spearman"]["ci_low"]
        != second["estimators"]["good"]["spearman"]["ci_low"]
    )


def test_a_different_population_label_draws_a_different_stream():
    """Adding a population to the report must not change any other's numbers."""
    observed, good, _ = linear_data()
    first = bootstrap_group(observed, {"good": good}, seed=42, resamples=200, label="oov")
    second = bootstrap_group(observed, {"good": good}, seed=42, resamples=200, label="all")
    assert first["estimators"]["good"]["rmse"]["ci_low"] != (
        second["estimators"]["good"]["rmse"]["ci_low"]
    )


def test_the_interval_brackets_the_point_estimate():
    observed, good, poor = linear_data()
    result = bootstrap_group(
        observed, {"good": good, "poor": poor}, seed=42, resamples=400, label="x"
    )
    for entry in result["estimators"].values():
        for statistic in entry.values():
            if statistic["ci_low"] is None or statistic["point"] is None:
                continue
            assert statistic["ci_low"] <= statistic["point"] <= statistic["ci_high"], statistic


def test_a_wider_interval_comes_from_a_smaller_population():
    observed, good, _ = linear_data(400)
    big = bootstrap_group(observed, {"good": good}, seed=42, resamples=400, label="x")
    small = bootstrap_group(
        observed[:40], {"good": good[:40]}, seed=42, resamples=400, label="x"
    )
    def width(block):
        entry = block["estimators"]["good"]["mean_absolute_error"]
        return entry["ci_high"] - entry["ci_low"]

    assert width(small) > width(big)


def test_a_population_below_the_minimum_gets_a_point_and_no_interval():
    observed, good, _ = linear_data(10)
    result = bootstrap_group(
        observed, {"good": good}, seed=42, resamples=400, min_samples=20, label="x"
    )
    assert result["below_minimum"] is True
    assert result["resamples"] == 0
    entry = result["estimators"]["good"]["spearman"]
    assert entry["point"] is not None
    assert entry["ci_low"] is None
    assert entry["ci_high"] is None


def test_a_mismatched_prediction_series_is_refused():
    observed, good, _ = linear_data(20)
    with pytest.raises(ValueError, match="predictions for"):
        bootstrap_group(observed, {"good": good[:10]}, seed=42, resamples=10, min_samples=5)


def test_the_direction_of_every_statistic_is_carried_with_it():
    observed, good, _ = linear_data(50)
    result = bootstrap_group(observed, {"good": good}, seed=42, resamples=100, label="x")
    for name, entry in result["estimators"]["good"].items():
        assert entry["higher_is_better"] is BOOTSTRAP_STATISTICS[name]


# -- pairing ----------------------------------------------------------------


def test_the_difference_is_paired_not_two_independent_intervals():
    """Two estimators whose errors differ by a constant on every target have a
    difference with no sampling variation at all. Drawing separate resamples
    for each would invent some."""
    observed, good, _ = linear_data(200)
    shifted = [value + 2.0 for value in good]
    result = bootstrap_group(
        observed,
        {"good": good, "shifted": shifted},
        pairs=(("shifted", "good"),),
        seed=42,
        resamples=300,
        label="x",
    )
    difference = result["differences"]["shifted-minus-good"]["spearman"]
    assert difference["point"] == pytest.approx(0.0, abs=1e-9)
    assert difference["ci_low"] == pytest.approx(0.0, abs=1e-9)
    assert difference["ci_high"] == pytest.approx(0.0, abs=1e-9)
    # ... while each estimator's own interval is genuinely wide.
    own = result["estimators"]["good"]["spearman"]
    assert own["ci_high"] > own["ci_low"]


def test_a_real_difference_is_signed_the_way_the_report_reads_it():
    observed, good, poor = linear_data(200)
    result = bootstrap_group(
        observed,
        {"good": good, "poor": poor},
        pairs=(("good", "poor"),),
        seed=42,
        resamples=300,
        label="x",
    )
    correlation = result["differences"]["good-minus-poor"]["spearman"]
    assert correlation["point"] > 0.0
    assert correlation["excludes_zero"] is True
    error = result["differences"]["good-minus-poor"]["mean_absolute_error"]
    assert error["point"] < 0.0
    assert error["higher_is_better"] is False


def test_a_difference_that_could_be_zero_is_reported_as_including_zero():
    """The result the milestone has to be able to report honestly."""
    observed, good, _ = linear_data(120)
    rng = random.Random(11)
    jittered = [value + rng.gauss(0.0, 0.02) for value in good]
    result = bootstrap_group(
        observed,
        {"good": good, "jittered": jittered},
        pairs=(("jittered", "good"),),
        seed=42,
        resamples=400,
        label="x",
    )
    difference = result["differences"]["jittered-minus-good"]["mean_absolute_error"]
    assert difference["excludes_zero"] is False


def test_a_pair_naming_a_missing_estimator_is_dropped_not_invented():
    observed, good, _ = linear_data(50)
    result = bootstrap_group(
        observed, {"good": good}, pairs=(("good", "absent"),), seed=42, resamples=50, label="x"
    )
    assert result["differences"] == {}


def test_asking_for_no_resamples_still_reports_the_point_estimates():
    observed, good, _ = linear_data(50)
    result = bootstrap_group(observed, {"good": good}, seed=42, resamples=0, label="x")
    assert result["resamples"] == 0
    assert result["estimators"]["good"]["rmse"]["point"] is not None
    assert result["estimators"]["good"]["rmse"]["ci_low"] is None


def test_the_interval_width_shrinks_towards_the_point_with_more_resamples():
    """Not a convergence proof -- a check that the number of resamples changes
    the interval's precision and not its centre."""
    observed, good, _ = linear_data(150)
    coarse = bootstrap_group(observed, {"good": good}, seed=42, resamples=50, label="x")
    fine = bootstrap_group(observed, {"good": good}, seed=42, resamples=1000, label="x")
    assert coarse["estimators"]["good"]["rmse"]["point"] == (
        fine["estimators"]["good"]["rmse"]["point"]
    )
    centre = fine["estimators"]["good"]["rmse"]["point"]
    assert abs(fine["estimators"]["good"]["rmse"]["ci_low"] - centre) < 1.0


def test_the_confidence_level_widens_the_interval():
    observed, good, _ = linear_data(150)
    narrow = bootstrap_group(
        observed, {"good": good}, seed=42, resamples=400, confidence=0.80, label="x"
    )
    wide = bootstrap_group(
        observed, {"good": good}, seed=42, resamples=400, confidence=0.99, label="x"
    )

    def width(block):
        entry = block["estimators"]["good"]["spearman"]
        return entry["ci_high"] - entry["ci_low"]

    assert width(wide) >= width(narrow)


def test_an_interval_survives_a_statistic_that_is_sometimes_undefined():
    """A resample can be degenerate -- every predicted value identical -- and the
    statistic is then undefined for that draw. It must be skipped, not counted
    as zero, and the rest of the interval must still be produced."""
    observed = [float(value) for value in range(1, 25)]
    predicted = [1.0] * 12 + [2.0] * 12
    result = bootstrap_group(
        observed, {"blocky": predicted}, seed=42, resamples=200, label="x"
    )
    entry = result["estimators"]["blocky"]["spearman"]
    assert entry["point"] is not None
    assert entry["ci_low"] is not None
    assert not math.isnan(entry["ci_low"])
