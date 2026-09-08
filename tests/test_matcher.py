"""The matcher: what it recognises inside a password, and what it must not."""

from __future__ import annotations

import dataclasses

import pytest

from conftest import NAMED_ENTITY_TIERS, TIER_ORDER, make_entry
from indicpass.password.dictionary import IndicDict
from indicpass.password.matcher import MatchClass, PasswordMatcher


def build(indicdict, matcher_settings) -> PasswordMatcher:
    return PasswordMatcher(
        [indicdict], matcher_settings, named_entity_tiers=NAMED_ENTITY_TIERS
    )


def tokens_of(matches, pattern: str) -> set[str]:
    return {match.token for match in matches if match.pattern == pattern}


# -- dictionary matching ---------------------------------------------------


def test_a_bare_dictionary_word_is_matched(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("namaste")
    assert "namaste" in tokens_of(matches, "indic_word")


def test_a_dictionary_word_is_found_inside_a_longer_password(indicdict, matcher_settings):
    """The point of the matcher: `namaste123` is not in any dictionary, `namaste` is."""
    matches = build(indicdict, matcher_settings).matches("namaste123")
    assert "namaste" in tokens_of(matches, "indic_word")


def test_a_dictionary_word_is_found_after_a_prefix(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("mybharat")
    indic = [m for m in matches if m.pattern == "indic_word"]
    assert any(m.token == "bharat" and m.start == 2 for m in indic)


def test_two_dictionary_words_are_both_found(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("merabharat")
    assert {"mera", "bharat"} <= tokens_of(matches, "indic_word")


def test_case_is_undone_for_the_lookup(indicdict, matcher_settings):
    matcher = build(indicdict, matcher_settings)
    for spelling in ("Namaste", "NAMASTE", "naMaste"):
        matches = matcher.matches(spelling)
        assert spelling in tokens_of(matches, "indic_word"), spelling


def test_the_case_transformation_is_recorded_on_the_match(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("Namaste")
    match = next(m for m in matches if m.pattern == "indic_word")
    assert match.detail["case_transformation"] == "capitalized"
    assert match.detail["case_variations"] == 2


def test_named_entity_tiers_are_flagged(indicdict, matcher_settings):
    matcher = build(indicdict, matcher_settings)
    name = next(m for m in matcher.matches("sharma") if m.pattern == "indic_word")
    word = next(m for m in matcher.matches("namaste") if m.pattern == "indic_word")
    assert name.detail["is_named_entity"] is True
    assert word.detail["is_named_entity"] is False


def test_a_match_reports_the_frequency_it_used_or_none(indicdict, ranked_indicdict,
                                                       matcher_settings):
    """A reader of a match must be able to tell evidence from fallback."""
    unranked = next(
        m for m in build(indicdict, matcher_settings).matches("namaste")
        if m.pattern == "indic_word"
    )
    assert unranked.detail["frequency"] is None
    assert unranked.detail["rank"] is None
    assert unranked.detail["rank_policy"] == "tier_fallback"

    ranked = next(
        m for m in build(ranked_indicdict, matcher_settings).matches("namaste")
        if m.pattern == "indic_word"
    )
    assert ranked.detail["frequency"] == 4.09
    assert ranked.detail["rank"] is not None
    assert ranked.detail["rank_policy"] == "observed_rank"
    assert ranked.detail["frequency_source"] is not None


# -- match classes ---------------------------------------------------------


def classes_of(matches) -> dict[str, str]:
    return {
        m.token: m.detail["match_class"] for m in matches if m.pattern == "indic_word"
    }


def test_the_whole_password_being_a_word_is_an_exact_match(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("namaste")
    assert classes_of(matches) == {"namaste": str(MatchClass.EXACT_WORD)}


def test_a_capitalised_whole_word_is_a_transformed_match(indicdict, matcher_settings):
    for spelling in ("Namaste", "NAMASTE", "naMaste"):
        matches = build(indicdict, matcher_settings).matches(spelling)
        assert classes_of(matches) == {spelling: str(MatchClass.TRANSFORMED_WORD)}, spelling


def test_a_long_proper_substring_is_a_substring_match(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("namaste123")
    assert classes_of(matches)["namaste"] == str(MatchClass.SUBSTRING_WORD)


def test_a_short_proper_substring_is_a_fragment(indicdict, matcher_settings):
    """`mera` is four letters and a real word; a three-letter hit inside a
    longer string is a coincidence two times in five."""
    dictionary = IndicDict.from_entries(
        [make_entry("jai", tier="human_romanized")], language="hin", tier_order=TIER_ORDER
    )
    matches = build(dictionary, matcher_settings).matches("jaixyz")
    assert classes_of(matches) == {"jai": str(MatchClass.FRAGMENT)}


def test_a_short_word_that_is_the_whole_password_is_not_a_fragment(matcher_settings):
    """`jai` on its own IS the password. There is no coincidence to correct."""
    dictionary = IndicDict.from_entries(
        [make_entry("jai", tier="human_romanized")], language="hin", tier_order=TIER_ORDER
    )
    matches = build(dictionary, matcher_settings).matches("jai")
    assert classes_of(matches) == {"jai": str(MatchClass.EXACT_WORD)}


def test_a_fragment_costs_more_than_the_same_hit_would_as_a_word(matcher_settings):
    dictionary = IndicDict.from_entries(
        [make_entry("jai", tier="human_romanized")], language="hin", tier_order=TIER_ORDER
    )
    matcher = build(dictionary, matcher_settings)
    whole = next(m for m in matcher.matches("jai") if m.pattern == "indic_word")
    fragment = next(m for m in matcher.matches("jaixyz") if m.pattern == "indic_word")

    assert fragment.cost > whole.cost
    assert fragment.detail["class_penalty"] == 10.0
    assert whole.detail["class_penalty"] == 1.0


def test_substring_matching_can_be_switched_off(indicdict, matcher_settings):
    """The "whole-password matches only" arm of the ablation."""
    settings = dataclasses.replace(matcher_settings, allow_substring_matches=False)
    matcher = PasswordMatcher([indicdict], settings, named_entity_tiers=NAMED_ENTITY_TIERS)

    assert tokens_of(matcher.matches("namaste"), "indic_word") == {"namaste"}
    assert tokens_of(matcher.matches("namaste123"), "indic_word") == set()


def test_fragment_matching_can_be_switched_off_without_losing_real_words(
    matcher_settings,
):
    dictionary = IndicDict.from_entries(
        [make_entry("jai"), make_entry("mera", tier="curated_other")],
        language="hin",
        tier_order=TIER_ORDER,
    )
    settings = dataclasses.replace(matcher_settings, allow_fragment_matches=False)
    matcher = PasswordMatcher([dictionary], settings, named_entity_tiers=NAMED_ENTITY_TIERS)

    assert tokens_of(matcher.matches("jaixyz"), "indic_word") == set()
    assert tokens_of(matcher.matches("meraxyz"), "indic_word") == {"mera"}


def test_the_substring_threshold_is_configuration_not_a_constant(
    indicdict, matcher_settings
):
    settings = dataclasses.replace(matcher_settings, min_substring_length=8)
    matcher = PasswordMatcher([indicdict], settings, named_entity_tiers=NAMED_ENTITY_TIERS)
    # namaste is 7 characters, so raising the bar to 8 reclasses it.
    assert classes_of(matcher.matches("namaste123"))["namaste"] == str(MatchClass.FRAGMENT)


@pytest.mark.parametrize("penalty", [1.0, 5.0, 100.0])
def test_the_class_penalty_multiplies_the_cost_exactly(indicdict, matcher_settings, penalty):
    settings = dataclasses.replace(
        matcher_settings,
        class_penalties={**matcher_settings.class_penalties, "substring_word": penalty},
    )
    matcher = PasswordMatcher([indicdict], settings, named_entity_tiers=NAMED_ENTITY_TIERS)
    match = next(m for m in matcher.matches("namaste123") if m.pattern == "indic_word")

    base = next(
        m
        for m in build(indicdict, matcher_settings).matches("namaste")
        if m.pattern == "indic_word"
    )
    assert match.guesses == pytest.approx(base.guesses * penalty)


# -- what must NOT match ---------------------------------------------------


def test_latin_letters_alone_do_not_make_an_indic_match(indicdict, matcher_settings):
    """`xkcd` is a run of valid characters. That is not the same as being a word."""
    matches = build(indicdict, matcher_settings).matches("xkcd")
    assert tokens_of(matches, "indic_word") == set()


def test_an_unrelated_english_word_is_not_an_indic_match(indicdict, matcher_settings):
    for password in ("password", "letmein", "football", "qwerty"):
        matches = build(indicdict, matcher_settings).matches(password)
        assert tokens_of(matches, "indic_word") == set(), password


def test_short_fragments_below_the_minimum_are_not_matched(indicdict, matcher_settings):
    """Two-letter hits would fire inside almost any string."""
    matches = build(indicdict, matcher_settings).matches("me")
    assert tokens_of(matches, "indic_word") == set()


# -- digits, years, symbols ------------------------------------------------


def test_a_trailing_digit_run_is_matched(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("namaste123")
    assert "123" in tokens_of(matches, "digits")


def test_a_plausible_year_is_matched_as_a_year(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("sharma2024")
    assert "2024" in tokens_of(matches, "year")


def test_a_year_costs_far_less_than_four_arbitrary_digits(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("sharma2024")
    year = next(m for m in matches if m.pattern == "year")
    digits = next(m for m in matches if m.pattern == "digits" and m.token == "2024")
    assert year.guesses < digits.guesses


def test_an_implausible_year_is_only_a_digit_run(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("sharma8317")
    assert tokens_of(matches, "year") == set()
    assert "8317" in tokens_of(matches, "digits")


def test_a_symbol_run_is_matched(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("sharma@123")
    assert "@" in tokens_of(matches, "symbols")


def test_sub_spans_of_a_digit_run_are_offered(indicdict, matcher_settings):
    """So a year followed by a stray digit can win if it is cheaper."""
    matches = build(indicdict, matcher_settings).matches("krishna19999")
    assert "1999" in tokens_of(matches, "year")
    assert "19999" in tokens_of(matches, "digits")


# -- repeats ---------------------------------------------------------------


def test_three_repeats_are_matched(indicdict, matcher_settings):
    matches = build(indicdict, matcher_settings).matches("namasteaaa")
    assert "aaa" in tokens_of(matches, "repeat")


def test_a_doubled_letter_inside_a_word_is_not_a_repeat(indicdict, matcher_settings):
    """`ll` is ordinary spelling; matching it would discount real words."""
    matches = build(indicdict, matcher_settings).matches("hello")
    assert tokens_of(matches, "repeat") == set()


# -- structure -------------------------------------------------------------


def test_every_match_covers_the_span_it_claims(indicdict, matcher_settings):
    password = "Namaste@2024aaa"
    for match in build(indicdict, matcher_settings).matches(password):
        assert password[match.start : match.end] == match.token
