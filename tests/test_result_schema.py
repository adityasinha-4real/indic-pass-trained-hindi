"""The serialised result: the shape reports rely on, and what may not be in it.

Two separate obligations meet here. The *schema* obligation is that a stored row
names its estimator, so a number cannot be misattributed six months later. The
*safety* obligation is that nothing written to disk contains password material.
The second is tested by scoring passwords assembled from distinctive strings and
then searching the JSON for them, because an assertion about a field name would
not catch a leak through a field nobody thought about.
"""

from __future__ import annotations

import json

import pytest

from indicpass.password.result import Match, PasswordStrengthResult, round_guesses

#: Scored throughout. Every piece is distinctive enough to find in a dump.
PASSWORD = "sharma@2024"
PIECES = ("sharma", "2024", "@", PASSWORD)


@pytest.fixture
def payload(meter_with_baseline):
    return meter_with_baseline.score(PASSWORD).to_dict()


# -- the documented shape --------------------------------------------------


def test_the_top_level_fields_are_present(payload):
    for key in (
        "password_length",
        "guess_number",
        "log10_guesses",
        "strength_score",
        "strength_label",
        "indicpass",
        "zxcvbn",
    ):
        assert key in payload, key


def test_the_indicpass_block_has_the_documented_keys(payload):
    assert set(payload["indicpass"]) == {
        "guesses",
        "log10_guesses",
        "score",
        "label",
        "matches",
    }


def test_the_baseline_block_is_named_for_its_estimator(payload):
    assert set(payload["zxcvbn"]) >= {"guesses", "log10_guesses", "score", "feedback"}


def test_the_nested_and_flat_views_are_the_same_numbers(payload):
    assert payload["indicpass"]["guesses"] == payload["guess_number"]
    assert payload["indicpass"]["score"] == payload["strength_score"]
    assert payload["zxcvbn"]["guesses"] == payload["baseline_guesses"]
    assert payload["zxcvbn"]["score"] == payload["baseline_score"]


def test_the_whole_payload_is_json_serialisable(payload):
    json.loads(json.dumps(payload, ensure_ascii=False))


def test_a_match_reports_its_class_and_pricing_policy(payload):
    indic = [m for m in payload["indicpass"]["matches"] if m["pattern"] == "indic_word"]
    assert indic
    for match in indic:
        assert match["match_class"] in {
            "exact_word",
            "transformed_word",
            "substring_word",
            "fragment",
        }
        assert match["rank_policy"] in {"observed_rank", "tier_fallback"}


# -- nothing written to disk carries the password --------------------------


def test_the_default_serialisation_contains_no_piece_of_the_password(payload):
    text = json.dumps(payload, ensure_ascii=False)
    for piece in PIECES:
        assert piece not in text, piece


def test_the_baseline_block_leaks_nothing_either(payload):
    """zxcvbn's own result echoes the password and every matched substring."""
    text = json.dumps(payload["zxcvbn"], ensure_ascii=False)
    for piece in PIECES:
        assert piece not in text, piece


def test_the_length_survives_because_it_is_not_content(payload):
    assert payload["password_length"] == len(PASSWORD)


def test_tokens_appear_only_when_explicitly_requested(meter_with_baseline):
    """The escape hatch the interactive CLI uses, printing to a terminal.

    The matched spans come back, not the password as one string -- a match is a
    substring, so `sharma` and `2024` appear separately.
    """
    shown = json.dumps(
        meter_with_baseline.score(PASSWORD).to_dict(include_tokens=True), ensure_ascii=False
    )
    assert "sharma" in shown
    assert "2024" in shown


def test_a_result_with_no_baseline_omits_the_block_rather_than_nulling_it(meter):
    payload = meter.score(PASSWORD).to_dict()
    assert "zxcvbn" not in payload
    assert payload["baseline_guesses"] is None


# -- numbers ---------------------------------------------------------------


def test_guesses_are_not_reported_to_absurd_precision(payload):
    """The estimate spans thirty orders of magnitude and is accurate to none of
    its trailing digits."""
    for value in (payload["guess_number"], payload["indicpass"]["guesses"]):
        assert float(f"{value:.6g}") == value


def test_rounding_leaves_the_special_values_alone():
    import math

    assert round_guesses(0.0) == 0.0
    assert round_guesses(math.inf) == math.inf
    assert math.isnan(round_guesses(math.nan))


def test_a_match_that_overflows_a_float_still_reports_a_finite_log():
    """A 400-character random span really does exceed the largest float."""
    match = Match(pattern="bruteforce", start=0, end=400, token="x" * 400, cost=560.0)
    described = match.describe()
    assert described["guesses"] == float("inf")
    assert described["log10_guesses"] == 560.0


def test_the_result_reports_a_score_inside_the_configured_scale(payload):
    assert 0 <= payload["strength_score"] <= 4
    assert isinstance(payload["strength_label"], str)


def test_an_empty_result_serialises(meter):
    empty = PasswordStrengthResult(
        password_length=0,
        guess_number=1.0,
        log10_guesses=0.0,
        strength_score=0,
        strength_label="Very Weak",
    )
    assert empty.to_dict()["matched_patterns"] == []
