"""The validation statistics.

Every metric here is checked against a case whose answer is known in closed
form -- a perfect line, a perfect reversal, a constant series, a hand-computed
mean -- rather than against a number a previous run produced. A statistics
module pinned to its own output cannot detect that it drifted.

The two properties that matter most are tested explicitly because getting
either wrong would quietly invert a conclusion:

* the **sign** of the error (predicted minus observed, so positive means the
  estimator called the password stronger than the attack found it);
* the **direction** of each metric (a correlation is won by the largest value,
  an error by the smallest), which :func:`best_by_metric` must not confuse.
"""

from __future__ import annotations

import json
import math

import pytest

from indicpass.password.validation import (
    ESTIMATOR_COLUMNS,
    ESTIMATOR_LABELS,
    METRIC_DIRECTION,
    ValidationRow,
    best_by_metric,
    calibration,
    combined_predictions,
    coverage_row,
    metrics,
    pearson,
    spearman,
    stratum_rows,
)


def row(
    sample_id: str,
    *,
    observed: float | None,
    predicted: float | dict[str, float],
    category: str = "indic_word",
    construction: str = "indic/lower",
    unseen: bool = False,
    case_variant: bool = False,
) -> ValidationRow:
    predictions = (
        predicted if isinstance(predicted, dict) else {"indicpass": float(predicted)}
    )
    return ValidationRow(
        sample_id=sample_id,
        category=category,
        construction=construction,
        length=8,
        covered=observed is not None,
        reference_rank=int(10**observed) if observed is not None else None,
        log10_reference_rank=observed,
        predictions=predictions,
        rule="word/lower" if observed is not None else None,
        unseen_stem=unseen,
        case_variant=case_variant,
    )


# -- correlations -----------------------------------------------------------


def test_pearson_is_one_on_a_perfect_line():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert pearson(xs, [2.0 * x + 5 for x in xs]) == pytest.approx(1.0)


def test_pearson_is_minus_one_on_a_perfect_reversal():
    xs = [1.0, 2.0, 3.0, 4.0]
    assert pearson(xs, [-3.0 * x for x in xs]) == pytest.approx(-1.0)


def test_pearson_matches_a_hand_computation():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    ys = [2.0, 4.0, 5.0, 4.0, 5.0]
    # dx = (-2,-1,0,1,2), dy = (-2,0,1,0,1): sum(dx*dy) = 6, sum(dx^2) = 10,
    # sum(dy^2) = 6.
    assert pearson(xs, ys) == pytest.approx(6 / math.sqrt(10 * 6), abs=1e-9)


def test_a_constant_series_has_no_correlation_rather_than_a_zero_one():
    """Zero is a finding; undefined is an absence of data. Reporting the second
    as the first would be a claim."""
    assert pearson([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None
    assert spearman([1.0, 1.0, 1.0], [1.0, 2.0, 3.0]) is None


def test_a_single_point_has_no_correlation():
    assert pearson([1.0], [2.0]) is None
    assert spearman([1.0], [2.0]) is None


def test_mismatched_series_are_an_error_not_a_truncation():
    with pytest.raises(ValueError, match="differ in length"):
        pearson([1.0, 2.0], [1.0])
    with pytest.raises(ValueError, match="differ in length"):
        spearman([1.0, 2.0], [1.0])


def test_spearman_is_one_on_any_monotone_relation():
    """The property that makes it the right statistic here: an estimator can
    order passwords perfectly while getting every number wrong."""
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert spearman(xs, [math.exp(x) for x in xs]) == pytest.approx(1.0)
    assert pearson(xs, [math.exp(x) for x in xs]) < 0.99


def test_spearman_averages_tied_ranks():
    """The brute-force floor gives whole blocks of passwords one estimate and
    the attack gives none of them one rank, so ties are the normal case."""
    tied = [5.0, 5.0, 5.0, 9.0]
    observed = [1.0, 2.0, 3.0, 4.0]
    # Ranks become 2,2,2,4 -- an ordering the estimator never expressed is not
    # invented, so the correlation is high but not perfect.
    value = spearman(tied, observed)
    assert value is not None
    assert 0.7 < value < 1.0


# -- metrics ----------------------------------------------------------------


def test_the_error_sign_says_the_estimator_called_it_stronger():
    over = row("a", observed=4.0, predicted=6.0)
    under = row("b", observed=4.0, predicted=2.0)
    assert over.error("indicpass") == pytest.approx(2.0)
    assert under.error("indicpass") == pytest.approx(-2.0)

    result = metrics([over], "indicpass")
    assert result.mean_signed_error == pytest.approx(2.0)
    assert result.direction == "over-estimates"
    assert metrics([under], "indicpass").direction == "under-estimates"


def test_a_calibrated_estimator_is_named_as_such():
    rows = [row(str(i), observed=4.0, predicted=4.1) for i in range(5)]
    assert metrics(rows, "indicpass").direction == "calibrated"


def test_every_error_statistic_matches_a_hand_computation():
    errors = (1.0, -2.0, 3.0, -0.25)
    rows = [
        row(str(index), observed=5.0, predicted=5.0 + error)
        for index, error in enumerate(errors)
    ]
    result = metrics(rows, "indicpass")

    assert result.samples == 4
    assert result.mean_signed_error == pytest.approx(sum(errors) / 4)
    assert result.median_signed_error == pytest.approx((-0.25 + 1.0) / 2)
    assert result.mean_absolute_error == pytest.approx(6.25 / 4)
    assert result.median_absolute_error == pytest.approx((1.0 + 2.0) / 2)
    assert result.rmse == pytest.approx(math.sqrt((1 + 4 + 9 + 0.0625) / 4))
    # |error| <= 0.5 for one of the four; <= 1.0 for two.
    assert result.within_half == pytest.approx(0.25)
    assert result.within_one == pytest.approx(0.5)
    # Strictly beyond the 0.5 band, in each direction.
    assert result.over_rate == pytest.approx(0.5)
    assert result.under_rate == pytest.approx(0.25)


def test_uncovered_rows_are_excluded_from_every_metric():
    rows = [
        row("a", observed=4.0, predicted=5.0),
        row("b", observed=None, predicted=99.0),
    ]
    result = metrics(rows, "indicpass")
    assert result.samples == 1
    assert result.mean_signed_error == pytest.approx(1.0)


def test_a_missing_estimator_column_is_skipped_rather_than_defaulted():
    rows = [row("a", observed=4.0, predicted={"indicpass": 5.0})]
    assert metrics(rows, "pcfg").samples == 0
    assert metrics(rows, "pcfg").spearman is None


def test_an_empty_population_produces_an_empty_metric_set_not_a_crash():
    result = metrics([], "indicpass", category="random")
    assert result.samples == 0
    assert result.category == "random"
    assert result.spearman is None


def test_metrics_can_be_restricted_to_one_category():
    rows = [
        row("a", observed=4.0, predicted=5.0, category="indic_word"),
        row("b", observed=4.0, predicted=9.0, category="random"),
    ]
    assert metrics(rows, "indicpass", category="indic_word").mean_signed_error == 1.0
    assert metrics(rows, "indicpass", category="random").mean_signed_error == 5.0


# -- winners ----------------------------------------------------------------


def test_the_winner_is_the_largest_correlation_and_the_smallest_error():
    good = metrics(
        [row(str(i), observed=float(i), predicted=float(i)) for i in range(1, 8)],
        "indicpass",
    )
    bad_rows = [
        row(str(i), observed=float(i), predicted=float(8 - i) + 5.0) for i in range(1, 8)
    ]
    bad = metrics(bad_rows, "indicpass")
    bad = type(bad)(**{**vars(bad), "estimator": "baseline"})

    winners = best_by_metric([good, bad])
    assert winners["spearman"]["estimator"] == "indicpass"
    assert winners["mean_absolute_error"]["estimator"] == "indicpass"
    assert winners["rmse"]["estimator"] == "indicpass"
    assert winners["within_1.0_log10"]["estimator"] == "indicpass"


def test_every_metric_declares_which_direction_wins():
    """A report that maximised an error would announce the worst estimator as
    the best, and nothing else in the pipeline would catch it."""
    for metric, higher_is_better in METRIC_DIRECTION.items():
        assert isinstance(higher_is_better, bool)
        assert "error" not in metric or higher_is_better is False
        assert not metric.startswith("within") or higher_is_better is True


def test_an_estimator_with_no_samples_cannot_win():
    empty = metrics([], "pcfg")
    real = metrics([row(str(i), observed=float(i), predicted=float(i)) for i in range(1, 6)],
                   "indicpass")
    winners = best_by_metric([empty, real])
    assert winners["spearman"]["estimator"] == "indicpass"


def test_winners_are_none_when_nothing_is_defined():
    assert best_by_metric([metrics([], "pcfg")])["spearman"] is None


# -- calibration ------------------------------------------------------------


def test_a_perfectly_calibrated_estimator_has_slope_one_and_intercept_zero():
    rows = [row(str(i), observed=float(i), predicted=float(i)) for i in range(1, 21)]
    fit = calibration(rows, "indicpass", bins=4)
    assert fit.slope == pytest.approx(1.0)
    assert fit.intercept == pytest.approx(0.0, abs=1e-9)
    assert fit.r_squared == pytest.approx(1.0)


def test_a_compressed_scale_shows_up_as_a_slope_above_one():
    """An estimator spreading passwords over half the range the attack does
    needs a slope of two to reach it -- which is the diagnostic."""
    rows = [
        row(str(i), observed=float(i), predicted=float(i) / 2.0) for i in range(1, 21)
    ]
    assert calibration(rows, "indicpass").slope == pytest.approx(2.0)


def test_a_constant_offset_shows_up_as_an_intercept():
    rows = [row(str(i), observed=float(i), predicted=float(i) + 3.0) for i in range(1, 21)]
    fit = calibration(rows, "indicpass")
    assert fit.slope == pytest.approx(1.0)
    assert fit.intercept == pytest.approx(-3.0)


def test_calibration_bins_are_equal_count_not_equal_width():
    """An equal-width bin over a clustered range puts everything in one bucket
    and reports nine empty ones."""
    values = [1.0] * 18 + [50.0, 100.0]
    rows = [row(str(i), observed=float(i), predicted=v) for i, v in enumerate(values)]
    fit = calibration(rows, "indicpass", bins=10)
    assert len(fit.bins) == 10
    assert {chunk.samples for chunk in fit.bins} == {2}


def test_calibration_reports_bias_per_bin():
    rows = [row(str(i), observed=float(i), predicted=float(i) + 2.0) for i in range(1, 11)]
    fit = calibration(rows, "indicpass", bins=5)
    assert all(chunk.mean_bias == pytest.approx(2.0) for chunk in fit.bins)


def test_a_constant_prediction_has_no_slope_but_still_has_a_bias():
    rows = [row(str(i), observed=float(i), predicted=7.0) for i in range(1, 11)]
    fit = calibration(rows, "indicpass", bins=2)
    assert fit.slope is None
    assert fit.r_squared is None
    assert fit.bins
    assert fit.bins[0].mean_bias != 0.0


def test_calibration_needs_two_points():
    fit = calibration([row("a", observed=1.0, predicted=1.0)], "indicpass")
    assert fit.samples == 1
    assert fit.slope is None


def test_points_are_thinned_and_can_be_switched_off():
    rows = [row(str(i), observed=float(i % 7), predicted=float(i)) for i in range(500)]
    assert len(calibration(rows, "indicpass", points=50).points) <= 51
    assert calibration(rows, "indicpass", points=0).points == ()


def test_calibration_points_identify_no_password():
    rows = [row(str(i), observed=float(i), predicted=float(i)) for i in range(1, 11)]
    payload = json.dumps(calibration(rows, "indicpass").to_dict())
    assert "password" not in payload
    assert all(isinstance(pair, list) and len(pair) == 2
               for pair in calibration(rows, "indicpass").to_dict()["points"])


# -- combinations -----------------------------------------------------------


def test_the_combined_columns_are_minima():
    values = combined_predictions(indicpass=8.0, pcfg=9.0, baseline=6.0)
    assert values["min_indicpass_baseline"] == 6.0
    assert values["min_pcfg_baseline"] == 6.0
    assert values["min_all"] == 6.0
    assert set(values) == set(ESTIMATOR_COLUMNS)


def test_a_missing_estimator_drops_its_columns_rather_than_being_substituted():
    """A min(PCFG, zxcvbn) computed without a PCFG would silently be zxcvbn."""
    without_pcfg = combined_predictions(indicpass=8.0, pcfg=None, baseline=6.0)
    assert "min_pcfg_baseline" not in without_pcfg
    assert "min_all" not in without_pcfg
    assert without_pcfg["min_indicpass_baseline"] == 6.0

    alone = combined_predictions(indicpass=8.0, pcfg=None, baseline=None)
    assert set(alone) == {"indicpass"}


def test_every_column_has_a_label():
    assert set(ESTIMATOR_LABELS) >= set(ESTIMATOR_COLUMNS)


# -- coverage and strata ----------------------------------------------------


def test_coverage_counts_the_two_derived_families():
    rows = [
        row("a", observed=4.0, predicted=5.0, case_variant=True),
        row("b", observed=None, predicted=5.0, unseen=True),
        row("c", observed=6.0, predicted=5.0),
    ]
    summary = coverage_row(rows)
    assert summary["targets"] == 3
    assert summary["covered"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["case_variant"] == 1
    assert summary["case_variant_covered"] == 1
    assert summary["unseen_stem"] == 1
    assert summary["unseen_stem_covered"] == 0
    assert summary["median_log10_rank"] == pytest.approx(5.0)


def test_coverage_of_an_empty_population_is_zero_not_an_error():
    assert coverage_row([], "random")["coverage"] == 0.0


def test_the_strata_partition_by_lexicon_membership():
    rows = [
        row("a", observed=4.0, predicted=5.0, unseen=True),
        row("b", observed=4.0, predicted=5.0, case_variant=True),
        row("c", observed=4.0, predicted=5.0),
    ]
    assert [r.sample_id for r in stratum_rows(rows, "unseen_spelling")] == ["a"]
    assert [r.sample_id for r in stratum_rows(rows, "case_variation")] == ["b"]
    assert [r.sample_id for r in stratum_rows(rows, "in_lexicon")] == ["b", "c"]


def test_an_unknown_stratum_is_refused():
    with pytest.raises(ValueError, match="Unknown stratum"):
        stratum_rows([], "vibes")


# -- schema -----------------------------------------------------------------


def test_a_row_serialises_without_the_password():
    payload = row("indic_word-0001", observed=4.0, predicted=5.0).to_dict()
    assert payload["sample_id"] == "indic_word-0001"
    assert payload["construction"] == "indic/lower"
    assert "password" not in payload
    assert "token" not in json.dumps(payload)


def test_a_row_keeps_the_two_quantities_apart():
    """``log10_reference_rank`` is an observation and ``predictions`` are model
    outputs. A schema that merged them would make the confusion inevitable."""
    payload = row("a", observed=4.0, predicted={"indicpass": 5.0, "pcfg": 6.0}).to_dict()
    assert payload["log10_reference_rank"] == 4.0
    assert payload["predictions"] == {"indicpass": 5.0, "pcfg": 6.0}
    assert "log10_guesses" not in payload


def test_the_metric_set_carries_its_own_direction_note():
    payload = metrics([row("a", observed=4.0, predicted=5.0)], "indicpass").to_dict()
    assert "STRONGER" in payload["error_note"]
    assert payload["label"] == ESTIMATOR_LABELS["indicpass"]
    assert set(payload) >= {
        "spearman",
        "pearson",
        "mean_signed_error",
        "median_signed_error",
        "mean_absolute_error",
        "median_absolute_error",
        "rmse",
        "within_0.5_log10",
        "within_1.0_log10",
        "over_estimate_rate",
        "under_estimate_rate",
    }


def test_an_uncovered_row_reports_no_error():
    assert row("a", observed=None, predicted=5.0).error("indicpass") is None
