"""CER and exact match, including the edge cases that silently corrupt scores."""

from __future__ import annotations

import pytest

from indicpass.metrics import (
    character_error_rate,
    corpus_cer,
    edit_distance,
    evaluate_predictions,
    exact_match,
)

# -- edit distance ---------------------------------------------------------


def test_identical_strings_have_distance_zero():
    assert edit_distance("नमस्ते", "नमस्ते") == 0


def test_single_substitution():
    assert edit_distance("कैसे", "कैसा") == 1


def test_single_insertion():
    assert edit_distance("हो", "हों") == 1


def test_single_deletion():
    assert edit_distance("नमस्ते", "नमस्त") == 1


def test_distance_is_symmetric():
    assert edit_distance("kitten", "sitting") == edit_distance("sitting", "kitten") == 3


def test_empty_against_non_empty_is_the_other_length():
    assert edit_distance("", "abcd") == 4
    assert edit_distance("abcd", "") == 4


def test_both_empty():
    assert edit_distance("", "") == 0


# -- per-example CER -------------------------------------------------------


def test_perfect_prediction_scores_zero():
    assert character_error_rate("नमस्ते", "नमस्ते") == 0.0


def test_one_wrong_character_in_four():
    assert character_error_rate("कैसा", "कैसे") == pytest.approx(0.25)


def test_completely_wrong_prediction_can_exceed_one():
    # Not clamped: a prediction three times too long really is worse than 1.0.
    assert character_error_rate("abcdef", "ab") == pytest.approx(2.0)


def test_empty_target_and_empty_prediction_is_zero_error():
    assert character_error_rate("", "") == 0.0


def test_empty_target_with_a_prediction_is_clamped_to_one():
    # The textbook formula divides by zero here; unbounded error from one
    # degenerate record would swamp a whole corpus average.
    assert character_error_rate("something", "") == 1.0


# -- corpus CER ------------------------------------------------------------


def test_corpus_cer_aggregates_before_dividing():
    # 1 error over 4 chars and 0 over 6 -> 1/10, NOT the mean of 0.25 and 0.
    predictions = ["कैसा", "नमस्ते"]
    targets = ["कैसे", "नमस्ते"]
    total_chars = len(targets[0]) + len(targets[1])
    assert corpus_cer(predictions, targets) == pytest.approx(1 / total_chars)


def test_corpus_cer_does_not_let_short_words_dominate():
    """The reason for aggregating: per-example averaging over-weights short words."""
    predictions = ["ब", "अबबबबबबबबब"]
    targets = ["अ", "अबबबबबबबबब"]

    per_example_mean = sum(
        character_error_rate(p, t) for p, t in zip(predictions, targets, strict=True)
    ) / 2
    assert per_example_mean == pytest.approx(0.5)  # one short word says "50% wrong"
    assert corpus_cer(predictions, targets) == pytest.approx(1 / 11)  # 1 char of 11


def test_corpus_cer_of_empty_input_is_zero():
    assert corpus_cer([], []) == 0.0


def test_mismatched_lengths_are_rejected():
    with pytest.raises(ValueError, match="predictions for"):
        corpus_cer(["a"], ["a", "b"])


# -- exact match -----------------------------------------------------------


def test_exact_match_is_strict():
    assert exact_match("नमस्ते", "नमस्ते")
    assert not exact_match("नमस्ते", "नमसते")


# -- the combined result ---------------------------------------------------


def test_evaluate_predictions_reports_both_metrics():
    result = evaluate_predictions(["कैसे", "नमसते"], ["कैसे", "नमस्ते"])
    assert result.count == 2
    assert result.exact_match == pytest.approx(0.5)
    assert 0 < result.cer < 1


def test_a_perfect_run_scores_zero_cer_and_full_exact_match():
    targets = ["नमस्ते", "कैसे", "हो"]
    result = evaluate_predictions(list(targets), targets)
    assert result.cer == 0.0
    assert result.exact_match == 1.0


def test_metrics_diverge_when_predictions_are_close_but_not_equal():
    """The ambiguity case: every word one character off.

    Exact match reads 0.0 and says the model is useless; CER reads ~0.17 and
    says it is nearly right. This gap is why best-checkpoint selection uses CER.
    """
    targets = ["नमस्ते", "कैसे", "अच्छा"]
    predictions = [t[:-1] + "क" for t in targets]

    result = evaluate_predictions(predictions, targets)
    assert result.exact_match == 0.0
    assert result.cer < 0.3


def test_evaluate_predictions_on_empty_input():
    result = evaluate_predictions([], [])
    assert result.count == 0 and result.cer == 0.0


def test_result_serialises_for_metrics_json():
    result = evaluate_predictions(["a"], ["a"])
    assert set(result.as_dict()) == {"cer", "exact_match", "count"}
