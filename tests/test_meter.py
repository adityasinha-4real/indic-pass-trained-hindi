"""The meter end to end, and the invariants the research claim rests on.

If any test in the "invariants" section starts failing, the guess model has
stopped describing an attacker and the benchmark built on it means nothing.
"""

from __future__ import annotations

import json
import math
import random

import pytest

from conftest import TIER_ORDER, build_meter, make_entry
from indicpass.password.dictionary import IndicDict

# -- basic behaviour -------------------------------------------------------


def test_a_dictionary_word_is_recognised(meter):
    result = meter.score("namaste")
    assert result.has_indic_match
    assert result.matched_indic_words == ("namaste",)


def test_a_word_with_a_numeric_suffix_finds_both_parts(meter):
    result = meter.score("namaste123")
    patterns = [match.pattern for match in result.matched_patterns]
    assert "indic_word" in patterns
    assert "digits" in patterns
    assert result.matched_indic_words == ("namaste",)


def test_a_name_with_a_year_finds_both_parts(meter):
    result = meter.score("sharma2024")
    patterns = [match.pattern for match in result.matched_patterns]
    assert patterns == ["indic_word", "year"]
    assert result.matched_names == ("sharma",)


def test_a_word_a_symbol_and_digits_decompose(meter):
    result = meter.score("sharma@123")
    assert [m.pattern for m in result.matched_patterns] == ["indic_word", "symbols", "digits"]


def test_a_password_of_two_dictionary_words(meter):
    result = meter.score("merabharat")
    assert set(result.matched_indic_words) == {"mera", "bharat"}


def test_an_unknown_string_gets_no_indic_match(meter):
    result = meter.score("xkcd")
    assert not result.has_indic_match
    assert result.matched_indic_words == ()


def test_the_score_is_in_range_and_labelled(meter):
    for password in ("a", "namaste", "namaste123", "Tr0ub4dor&3", "x" * 40):
        result = meter.score(password)
        assert 0 <= result.strength_score <= 4
        assert result.strength_label in meter.scale.labels


def test_log10_guesses_is_the_log_of_the_guess_number(meter):
    result = meter.score("namaste123")
    assert result.log10_guesses == pytest.approx(math.log10(result.guess_number))


def test_the_duplicate_named_fields_agree(meter):
    result = meter.score("namaste123")
    assert result.indicpass_guesses == result.guess_number
    assert result.indicpass_score == result.strength_score


def test_without_a_baseline_the_comparison_fields_stay_empty(meter):
    """Absent, not zero. A missing baseline must be unmistakable in a report,
    because no comparative claim may be made from a run that lacked one."""
    result = meter.score("namaste123")
    assert result.baseline is None
    assert result.baseline_guesses is None
    assert result.baseline_score is None
    assert "zxcvbn" not in result.to_dict()


def test_a_baseline_is_carried_on_every_result(meter_with_baseline):
    result = meter_with_baseline.score("namaste123")
    assert result.baseline is not None
    assert result.baseline_guesses == result.baseline.guesses
    assert result.baseline_score == result.baseline.score
    assert 0 <= result.baseline_score <= 4


def test_the_two_estimators_are_scored_from_the_same_call(meter_with_baseline):
    """Same password, same call. A benchmark that re-derived one side later
    could silently compare against a different password or a different config.
    """
    result = meter_with_baseline.score("sharma2024")
    payload = result.to_dict()
    assert payload["indicpass"]["guesses"] == payload["guess_number"]
    assert payload["zxcvbn"]["guesses"] == result.baseline.guesses


# -- the invariants --------------------------------------------------------


def test_an_indic_word_is_far_weaker_than_a_random_string_of_the_same_length(meter):
    """The central claim: knowing the lexicon reveals weakness length cannot see."""
    known = meter.score("namaste")
    random_like = meter.score("qxzjvwk")

    assert known.password_length == random_like.password_length
    assert known.log10_guesses < random_like.log10_guesses
    # Not a rounding difference -- orders of magnitude.
    assert random_like.log10_guesses - known.log10_guesses > 2


def test_a_numeric_suffix_helps_but_does_not_rescue_a_weak_word(meter):
    """`namaste123` must beat `namaste`, and still lose to a random 10-character string."""
    bare = meter.score("namaste")
    suffixed = meter.score("namaste123")
    random_like = meter.score("qxzjvwkmrt")

    assert suffixed.log10_guesses > bare.log10_guesses
    assert suffixed.log10_guesses < random_like.log10_guesses


def test_a_predictable_suffix_adds_only_a_bounded_amount(meter):
    """Three digits are worth about 10^3 attempts plus structure, not a new class."""
    bare = meter.score("namaste")
    suffixed = meter.score("namaste123")
    added = suffixed.log10_guesses - bare.log10_guesses
    assert 0 < added < 8


def test_capitalisation_barely_changes_the_estimate(meter):
    """A meter that rewards a shift key teaches people the wrong lesson."""
    lower = meter.score("namaste")
    capital = meter.score("Namaste")
    shouted = meter.score("NAMASTE")

    for variant in (capital, shouted):
        assert variant.log10_guesses > lower.log10_guesses
        assert variant.log10_guesses - lower.log10_guesses < 1  # under a factor of 10


def test_a_year_suffix_is_weaker_than_arbitrary_digits(meter):
    year = meter.score("sharma2024")
    arbitrary = meter.score("sharma8317")
    assert year.log10_guesses < arbitrary.log10_guesses


def test_random_strings_are_not_systematically_cheap(meter):
    """Guarding against a matcher that finds "words" everywhere."""
    for password in ("qxzjvwkm", "hjkfdsap", "zvbnmqwe", "plmoknij"):
        result = meter.score(password)
        assert result.log10_guesses > 8, password


def test_longer_random_strings_score_higher(meter):
    scores = [meter.score("qxzjvwkmrtbn"[:n]).log10_guesses for n in (6, 8, 10, 12)]
    assert scores == sorted(scores)


def test_finding_a_word_can_only_lower_the_estimate(meter, indicdict, matcher_settings,
                                                    scoring_settings, scale):
    """Adding lexical knowledge is a minimum over more options; it cannot add strength.

    This is the property that makes the Milestone 2 comparison meaningful: any
    difference from the baseline must be IndicPass finding weakness, never
    IndicPass inventing strength.
    """
    from indicpass.password.dictionary import IndicDict
    from indicpass.password.meter import IndicPassMeter

    empty = IndicPassMeter(
        [IndicDict.from_entries([], language="hin", tier_order=tuple(indicdict.tiers))],
        matcher_settings=matcher_settings,
        scoring_settings=scoring_settings,
        scale=scale,
    )
    for password in ("namaste", "namaste123", "sharma@123", "merabharat", "xkcd"):
        with_dict = meter.score(password).log10_guesses
        without = empty.score(password).log10_guesses
        assert with_dict <= without + 1e-9, password


def test_an_empty_password_is_the_weakest_possible(meter):
    result = meter.score("")
    assert result.password_length == 0
    assert result.strength_score == 0


# -- the partial-match pathology -------------------------------------------
#
# A 298k-entry dictionary contains a great many short strings that are not
# words anybody would attack with. Measured on the real one, two of every five
# three-letter strings are keys, and 95% of random ten-character strings
# contain some key. These tests pin down what the meter is allowed to conclude
# from that.


@pytest.fixture
def overlapping_meter(matcher_settings, scoring_settings, scale):
    """A dictionary holding both `namaste` and its accidental suffix `maste`."""
    dictionary = IndicDict.from_entries(
        [
            make_entry("namaste", tier="human_romanized", frequency=4.09),
            make_entry("maste", "मस्ते", tier="mined", source="IndicCorp"),
            make_entry("bharat", "भारत", tier="curated_entities", frequency=6.38),
            make_entry("mera", "मेरा", tier="mined", source="IndicCorp", frequency=5.78),
        ],
        language="hin",
        tier_order=TIER_ORDER,
    )
    return build_meter(dictionary, matcher_settings, scoring_settings, scale)


def test_a_word_beats_a_fragment_of_itself(overlapping_meter):
    """The milestone's headline case.

    `namaste` must be read as the word `namaste`, not as two unexplained
    characters followed by the dictionary entry `maste`. Explaining the whole
    password with one word is both cheaper and the truth.
    """
    result = overlapping_meter.score("namaste")
    assert result.matched_indic_words == ("namaste",)
    assert [m.pattern for m in result.matched_patterns] == ["indic_word"]
    assert result.matched_patterns[0].detail["match_class"] == "exact_word"


def test_a_word_beats_a_fragment_of_itself_with_a_suffix(overlapping_meter):
    result = overlapping_meter.score("namaste2024")
    assert result.matched_indic_words == ("namaste",)


def test_the_fragment_reading_survives_when_the_word_is_genuinely_absent(
    matcher_settings, scoring_settings, scale
):
    """The other half of the same claim, and the reason not to simply ban
    substring matches: when `namaste` is NOT in the dictionary, `?? + maste` is
    a real attack path and suppressing it would OVERSTATE the password.
    """
    dictionary = IndicDict.from_entries(
        [make_entry("maste", "मस्ते", tier="mined", source="IndicCorp")],
        language="hin",
        tier_order=TIER_ORDER,
    )
    meter = build_meter(dictionary, matcher_settings, scoring_settings, scale)
    assert meter.score("namaste").matched_indic_words == ("maste",)


def test_a_random_string_is_not_explained_away_by_tiny_fragments(
    matcher_settings, scoring_settings, scale
):
    """With enough three-letter entries a matcher can "read" anything.

    The estimate for a random string must stay within a whisker of what a
    dictionary-free meter says, or every benchmark advantage on random controls
    is an artefact of the wordlist's junk.
    """
    letters = "abcdefghijklmnopqrstuvwxyz"
    rng = random.Random(7)
    # Every three-letter string, i.e. the worst case the real dictionary is a
    # 40% sample of.
    dictionary = IndicDict.from_entries(
        [
            make_entry(a + b + c, tier="mined", source="IndicCorp")
            for a in letters
            for b in letters
            for c in letters
        ],
        language="hin",
        tier_order=TIER_ORDER,
    )
    stuffed = build_meter(dictionary, matcher_settings, scoring_settings, scale)
    empty = build_meter(
        IndicDict.from_entries([], language="hin", tier_order=TIER_ORDER),
        matcher_settings,
        scoring_settings,
        scale,
    )

    for _ in range(25):
        password = "".join(rng.choice(letters) for _ in range(10))
        assert empty.score(password).log10_guesses - stuffed.score(password).log10_guesses < 1.0


def test_a_frequency_ranked_word_is_far_cheaper_than_a_tier_priced_one(
    meter, ranked_meter
):
    """What the frequency source bought.

    `bharat` is one of the commonest words in Hindi. Priced by its provenance
    tier it costs thousands of guesses; priced by its measured rank it costs a
    handful. The tier fallback is a policy for the unknown, not a substitute.
    """
    assert ranked_meter.score("bharat").log10_guesses < meter.score("bharat").log10_guesses


def test_two_common_words_joined_are_still_weak(ranked_meter):
    """`merabharat` is two of the commonest words in Hindi.

    Under the tier fallback this scored 4 of 4 -- "Very Strong" -- because
    provenance said nothing about how common the words were. It is a
    dictionary attack of a few hundred thousand guesses.
    """
    result = ranked_meter.score("merabharat")
    assert set(result.matched_indic_words) == {"mera", "bharat"}
    assert result.strength_score <= 2


# -- the password never leaks ---------------------------------------------


def test_serialising_redacts_the_matched_substrings(meter):
    result = meter.score("namaste123")
    payload = result.to_dict()
    text = json.dumps(payload, ensure_ascii=False)

    assert "namaste" not in text
    assert "123" not in text
    # Counts survive, so a report can still say "one dictionary word".
    assert payload["matched_indic_words"] == 1


def test_the_estimated_components_carry_no_tokens(meter):
    result = meter.score("sharma@123")
    for component in result.estimated_components:
        assert "token" not in component


def test_the_native_form_is_redacted_with_the_token(meter):
    """It reverse-maps: anyone with the dictionary reads the spelling off it."""
    result = meter.score("namaste123")
    redacted = result.to_dict()
    assert all("native_form" not in m for m in redacted["matched_patterns"])
    assert "नमस्ते" not in json.dumps(redacted, ensure_ascii=False)

    shown = result.to_dict(include_tokens=True)
    assert any("native_form" in m for m in shown["matched_patterns"])


def test_guess_counts_are_not_reported_to_absurd_precision(meter):
    """The estimate spans thirty orders of magnitude; 16 digits would be a lie."""
    guesses = meter.score("namaste123").to_dict()["guess_number"]
    assert f"{guesses:.10g}".count("0") < 12  # not 3524551264.000004
    assert float(f"{guesses:.6g}") == guesses


def test_tokens_are_available_only_on_request(meter):
    payload = meter.score("namaste123").to_dict(include_tokens=True)
    assert payload["matched_indic_words"] == ["namaste"]


def test_warnings_never_quote_the_password(meter):
    result = meter.score("namaste123")
    assert result.warnings
    for note in result.warnings:
        assert "namaste" not in note
        assert "123" not in note


def test_a_dictionary_hit_is_reported_as_a_warning(meter):
    result = meter.score("namaste")
    assert any("dictionary word" in note for note in result.warnings)


def test_a_name_is_reported_as_a_name(meter):
    result = meter.score("sharma")
    assert any("dictionary name" in note for note in result.warnings)


def test_an_unrecognised_password_says_so(meter):
    result = meter.score("qxzjvwkm")
    assert any("No known word" in note for note in result.warnings)
