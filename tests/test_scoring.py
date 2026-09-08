"""The guess model: optimal segmentation, and the 0-4 scale."""

from __future__ import annotations

import math
from itertools import pairwise

import pytest

from conftest import NAMED_ENTITY_TIERS
from indicpass.password.matcher import PasswordMatcher
from indicpass.password.result import Match, guesses_from_log10
from indicpass.password.scoring import StrengthScale, best_segmentation

# -- the scale -------------------------------------------------------------


def test_the_score_is_the_number_of_thresholds_reached(scale):
    assert scale.score(math.log10(1)) == 0
    assert scale.score(math.log10(999)) == 0
    assert scale.score(math.log10(1e3)) == 1
    assert scale.score(math.log10(1e7)) == 2
    assert scale.score(math.log10(1e9)) == 3
    assert scale.score(math.log10(1e11)) == 4


def test_labels_line_up_with_scores(scale):
    assert scale.label(0) == "Very Weak"
    assert scale.label(4) == "Very Strong"


def test_a_threshold_boundary_belongs_to_the_higher_band(scale):
    """`>=`, not `>`. Stated in a test so it cannot drift silently."""
    assert scale.score(math.log10(1e6)) == 2


def test_an_overflowing_guess_count_still_scores(scale):
    assert scale.score(math.inf) == 4


def test_the_scale_rejects_a_mismatched_label_count():
    with pytest.raises(ValueError, match="need"):
        StrengthScale([1e3, 1e6], ["a", "b"])


def test_the_scale_rejects_unordered_thresholds():
    with pytest.raises(ValueError, match="strictly increase"):
        StrengthScale([1e6, 1e3], ["a", "b", "c"])


def test_the_scale_rejects_a_non_positive_threshold():
    with pytest.raises(ValueError, match="positive"):
        StrengthScale([0, 1e3], ["a", "b", "c"])


# -- segmentation ----------------------------------------------------------


def matches_for(password, indicdict, matcher_settings):
    return PasswordMatcher(
        [indicdict], matcher_settings, named_entity_tiers=NAMED_ENTITY_TIERS
    ).matches(password)


def score_of(password, indicdict, matcher_settings, scoring_settings):
    return best_segmentation(
        password, matches_for(password, indicdict, matcher_settings), scoring_settings
    )


def test_a_segmentation_covers_the_whole_password(
    indicdict, matcher_settings, scoring_settings
):
    password = "namaste@2024"
    result = score_of(password, indicdict, matcher_settings, scoring_settings)

    covered = sorted((m.start, m.end) for m in result.matches)
    assert covered[0][0] == 0
    assert covered[-1][1] == len(password)
    for (_, end), (start, _) in pairwise(covered):
        assert end == start, "segments must abut with no gap or overlap"


def test_an_empty_password_does_not_crash(scoring_settings):
    result = best_segmentation("", [], scoring_settings)
    assert result.matches == ()
    assert result.log10_guesses == 0.0


def test_a_dictionary_word_beats_brute_forcing_it(
    indicdict, matcher_settings, scoring_settings
):
    known = score_of("namaste", indicdict, matcher_settings, scoring_settings)
    unknown = score_of("xkcdxkc", indicdict, matcher_settings, scoring_settings)

    assert len(known.matches) == 1
    assert known.matches[0].pattern == "indic_word"
    assert unknown.matches[0].pattern == "bruteforce"
    assert known.log10_guesses < unknown.log10_guesses


def test_adjacent_unexplained_spans_merge_into_one(
    indicdict, matcher_settings, scoring_settings
):
    """Splitting a random string costs the structure factor, so the search won't."""
    result = score_of("xkcdwqzv", indicdict, matcher_settings, scoring_settings)
    assert len(result.matches) == 1
    assert result.matches[0].pattern == "bruteforce"


def test_the_search_takes_the_attacker_s_cheapest_route(scoring_settings):
    """Given two coverings, the cheaper total wins -- not the one with fewer parts.

    Eight characters, so the bruteforce span the search always adds for itself
    (26**8, about 2e11) is comfortably the expensive option.
    """
    cheap_a = Match.from_guesses("indic_word", 0, 4, "abcd", 10)
    cheap_b = Match.from_guesses("digits", 4, 8, "efgh", 10)

    result = best_segmentation("abcdefgh", [cheap_a, cheap_b], scoring_settings)
    # 2! * 10 * 10 + 10^4 = 10,200, against 26^8 for a single unexplained span.
    assert [m.pattern for m in result.matches] == ["indic_word", "digits"]
    assert result.log10_guesses == pytest.approx(math.log10(2 * 10 * 10 + 1e4))


def test_the_structure_factor_is_a_floor_on_a_split_explanation(scoring_settings):
    """A k-segment reading costs at least D^(k-1), however cheap its pieces.

    Two free segments still cost the 10^4 it takes to reach a two-part
    structure. Without this floor, finding enough cheap pieces would drive any
    password's estimate towards zero.
    """
    part_a = Match.from_guesses("indic_word", 0, 2, "ab", 1)
    part_b = Match.from_guesses("digits", 2, 4, "cd", 1)

    result = best_segmentation("abcd", [part_a, part_b], scoring_settings)
    assert len(result.matches) == 2
    assert result.log10_guesses >= math.log10(scoring_settings.structure_factor)


def test_more_segments_carry_a_higher_floor(scoring_settings):
    """D^(k-1) grows with k, so a three-part reading starts above a two-part one."""
    two = best_segmentation(
        "abcd",
        [
            Match.from_guesses("indic_word", 0, 2, "ab", 1),
            Match.from_guesses("digits", 2, 4, "cd", 1),
        ],
        scoring_settings,
    )
    three = best_segmentation(
        "abcdef",
        [
            Match.from_guesses("indic_word", 0, 2, "ab", 1),
            Match.from_guesses("digits", 2, 4, "cd", 1),
            Match.from_guesses("symbols", 4, 6, "ef", 1),
        ],
        scoring_settings,
    )
    assert three.log10_guesses > two.log10_guesses


def test_segmentation_depth_cannot_leave_a_password_unscorable(
    indicdict, matcher_settings, scoring_settings
):
    """Capping depth may over-estimate; it must never fail to produce a result."""
    shallow = type(scoring_settings)(
        structure_factor=scoring_settings.structure_factor,
        min_guesses=scoring_settings.min_guesses,
        max_segmentation_depth=1,
        bruteforce_cardinality=scoring_settings.bruteforce_cardinality,
        character_class_sizes=scoring_settings.character_class_sizes,
    )
    password = "namaste@2024!x"
    result = best_segmentation(
        password, matches_for(password, indicdict, matcher_settings), shallow
    )
    assert len(result.matches) == 1
    assert result.log10_guesses > 0


def test_capping_the_depth_never_flatters_a_password(
    indicdict, matcher_settings, scoring_settings
):
    password = "namaste@2024"
    deep = score_of(password, indicdict, matcher_settings, scoring_settings)
    shallow_settings = type(scoring_settings)(
        structure_factor=scoring_settings.structure_factor,
        min_guesses=scoring_settings.min_guesses,
        max_segmentation_depth=1,
        bruteforce_cardinality=scoring_settings.bruteforce_cardinality,
        character_class_sizes=scoring_settings.character_class_sizes,
    )
    shallow = best_segmentation(
        password, matches_for(password, indicdict, matcher_settings), shallow_settings
    )
    assert shallow.log10_guesses >= deep.log10_guesses


# -- overflow --------------------------------------------------------------


def test_a_huge_guess_count_becomes_inf_rather_than_raising():
    assert guesses_from_log10(400) == math.inf
    assert guesses_from_log10(3) == pytest.approx(1000)


def test_a_very_long_random_password_scores_without_overflowing(
    indicdict, matcher_settings, scoring_settings
):
    password = "qwzx" * 60
    result = score_of(password, indicdict, matcher_settings, scoring_settings)
    assert math.isfinite(result.log10_guesses)
    assert result.log10_guesses > 100
