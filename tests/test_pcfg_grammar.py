"""The grammar: n-gram, priors, terminal distributions, and the parse.

These tests are arithmetic wherever they can be. A probability model whose
tests only check that numbers came out is a model nobody can argue with, so
where a quantity has a closed form -- a geometric prior, a case normaliser, a
uniform category prior -- the test states the form and checks it.
"""

from __future__ import annotations

import math
import random
from itertools import pairwise

import pytest

from conftest import TIER_ORDER, make_entry
from indicpass.password.dictionary import IndicDict
from indicpass.password.pcfg.grammar import (
    CATEGORY_DIGITS,
    CATEGORY_SYMBOLS,
    CATEGORY_UNKNOWN,
    CATEGORY_WORD,
    CATEGORY_YEAR,
    PCFG_CATEGORIES,
    CaseModel,
    GrammarSettings,
    PcfgGrammar,
    WordDistribution,
)
from indicpass.password.pcfg.ngram import END_OF_WORD, NGRAM_ALPHABET, CharacterNgram
from indicpass.password.pcfg.parser import best_derivation

SCORING = {
    "year_range": (1900, 2035),
    "digits_per_position": 10,
    "symbol_alphabet_size": 33,
    "bruteforce_cardinality": 10,
    "character_class_sizes": {"lowercase": 26, "uppercase": 26, "digits": 10, "symbols": 33},
}


@pytest.fixture
def settings() -> GrammarSettings:
    return GrammarSettings.from_config(
        {"grammar": {"ngram_order": 3, "max_segments": 5, "max_run_length": 12}}, SCORING
    )


@pytest.fixture
def grammar(ranked_indicdict, settings) -> PcfgGrammar:
    return PcfgGrammar.train(ranked_indicdict, settings)


# -- the character n-gram --------------------------------------------------


def test_the_alphabet_is_the_letters_plus_an_end_symbol():
    """The end symbol is what makes this a distribution over strings, not characters."""
    assert len(NGRAM_ALPHABET) == 27
    assert END_OF_WORD in NGRAM_ALPHABET


def test_every_context_distribution_sums_to_one():
    model = CharacterNgram.train(["namaste", "bharat", "pyaar"], order=3)
    for context in ("", "n", "na", "zz", "qqq"):
        assert sum(model.distribution(context).values()) == pytest.approx(1.0)


def test_an_unseen_context_falls_back_rather_than_failing():
    """Witten-Bell's whole job. A context with no counts keeps the shorter model."""
    model = CharacterNgram.train(["bharat"], order=4)
    unseen = model.distribution("zqx")
    unigram = model.distribution("")
    assert unseen == unigram


def test_a_trained_spelling_is_more_probable_than_a_random_one():
    """The property the model exists for: shape, not membership."""
    words = ["bharat", "bhagwan", "bharti", "bhavna", "bhasha", "bhajan", "bhakti"]
    model = CharacterNgram.train(words, order=4)
    assert model.log10_probability("bhagat") > model.log10_probability("qxzjvk")


def test_probabilities_are_negative_logarithms_never_positive():
    model = CharacterNgram.train(["namaste", "bharat"], order=3)
    for word in ("namaste", "bharat", "xyzzy", "a"):
        assert model.log10_probability(word) < 0.0


def test_an_out_of_alphabet_character_is_refused_not_scored():
    """`-inf` means 'this category cannot explain this span', not 'very unlikely'."""
    model = CharacterNgram.train(["bharat"], order=3)
    assert model.log10_probability("bhar4t") == -math.inf
    assert model.log10_probability("") == -math.inf


def test_the_same_words_in_a_different_order_train_the_same_model():
    """Determinism is what lets the artefact carry a fingerprint."""
    words = ["namaste", "bharat", "pyaar", "dosti"]
    first = CharacterNgram.train(words, order=4)
    second = CharacterNgram.train(list(reversed(words)), order=4)
    for probe in ("bharat", "namaste", "qxz"):
        assert first.log10_probability(probe) == second.log10_probability(probe)


def test_sampling_is_reproducible_from_a_seed():
    model = CharacterNgram.train(["namaste", "bharat", "pyaar", "dosti"], order=3)
    first = [model.sample(random.Random(11)) for _ in range(5)]
    second = [model.sample(random.Random(11)) for _ in range(5)]
    assert first == second


def test_a_sampled_spelling_is_made_of_the_alphabet():
    model = CharacterNgram.train(["namaste", "bharat"], order=3)
    rng = random.Random(3)
    for _ in range(50):
        spelling = model.sample(rng, max_length=12)
        assert len(spelling) <= 12
        assert all(char in NGRAM_ALPHABET for char in spelling)


def test_the_order_must_be_positive():
    with pytest.raises(ValueError, match="order >= 1"):
        CharacterNgram.train(["bharat"], order=0)


# -- the case model --------------------------------------------------------


def test_the_case_model_is_a_distribution_over_every_surface():
    """Sums to 1 over all 2**L casings. This is the step Milestone 2 did not take.

    Milestone 2 used the variation count as a cost multiplier, which gave an
    all-lower-case word a multiplier of 1 and therefore a "distribution" summing
    to far more than one. A PCFG cannot use that; the normaliser is what turns
    the same weighting into a probability.
    """
    for length in (1, 2, 3, 5, 8):
        total = sum(
            10 ** CaseModel.log10_probability(_surface(length, mask))
            for mask in range(2**length)
        )
        assert total == pytest.approx(1.0), length


def _surface(length: int, mask: int) -> str:
    letters = "abcdefghij"[:length]
    return "".join(
        char.upper() if mask >> index & 1 else char for index, char in enumerate(letters)
    )


def test_capitalising_costs_exactly_one_bit_of_probability():
    """Two variations, so half the probability -- log10(2), not orders of magnitude."""
    lower = CaseModel.log10_probability("bharat")
    upper = CaseModel.log10_probability("Bharat")
    assert lower - upper == pytest.approx(math.log10(2))


def test_the_three_ordinary_case_patterns_cost_the_same():
    values = {
        CaseModel.log10_probability(surface)
        for surface in ("Bharat", "BHARAT", "bharaT")
    }
    assert len(values) == 1


def test_genuinely_mixed_case_costs_more_than_the_ordinary_patterns():
    assert CaseModel.log10_probability("BhArAt") < CaseModel.log10_probability("Bharat")


def test_a_case_draw_returns_a_probability_the_model_agrees_with():
    rng = random.Random(5)
    drawn = {CaseModel.sample_log10(rng, 6) for _ in range(200)}
    enumerated = {
        round(CaseModel.log10_probability(_surface(6, mask)), 9) for mask in range(64)
    }
    assert {round(value, 9) for value in drawn} <= enumerated


# -- the word distribution -------------------------------------------------


def test_the_word_distribution_normalises_over_the_dictionary(ranked_indicdict):
    words = WordDistribution.train(ranked_indicdict)
    total = sum(
        10 ** words.log10_probability(entry) for entry in ranked_indicdict.entries.values()
    )
    assert total == pytest.approx(1.0)


def test_a_commoner_word_gets_more_probability(ranked_indicdict):
    words = WordDistribution.train(ranked_indicdict)
    # bharat has Zipf 6.38 in the fixture, jaihind 2.20.
    common = words.log10_probability(ranked_indicdict.entries["bharat"])
    rare = words.log10_probability(ranked_indicdict.entries["jaihind"])
    assert common > rare


def test_an_unobserved_entry_never_outranks_an_observed_one():
    """The bound the fallback rests on: absent from the table means not commoner
    than the rarest word on it."""
    entries = [
        make_entry("bharat", tier="human_romanized", frequency=6.38),
        make_entry("jaihind", tier="human_romanized", frequency=2.20),
        make_entry("kuchbhi", tier="human_romanized"),
    ]
    dictionary = IndicDict.from_entries(entries, language="hin", tier_order=TIER_ORDER)
    words = WordDistribution.train(dictionary)

    unobserved = words.log10_probability(dictionary.entries["kuchbhi"])
    rarest = words.log10_probability(dictionary.entries["jaihind"])
    assert unobserved <= rarest


def test_tier_weights_follow_measured_coverage():
    """Not a policy pulled from the air: the ratio is counted from the data."""
    entries = [
        make_entry("bharat", tier="human_romanized", frequency=6.38),
        make_entry("jaihind", tier="human_romanized"),
        make_entry("kuchbhi", tier="mined"),
        make_entry("aurbhi", tier="mined"),
    ]
    dictionary = IndicDict.from_entries(entries, language="hin", tier_order=TIER_ORDER)
    words = WordDistribution.train(dictionary)
    # human_romanized: (1 ranked + 1) / (2 + 1); mined: (0 + 1) / (2 + 1)
    assert words.tier_weights["human_romanized"] == pytest.approx(2 / 3)
    assert words.tier_weights["mined"] == pytest.approx(1 / 3)


def test_the_excluded_policy_removes_unobserved_entries_entirely(indicdict):
    words = WordDistribution.train(indicdict, policy="excluded")
    entry = next(iter(indicdict.entries.values()))
    assert words.log10_probability(entry) == -math.inf


def test_an_unknown_unranked_policy_is_refused(indicdict):
    with pytest.raises(ValueError, match="Unknown unranked_policy"):
        WordDistribution.train(indicdict, policy="vibes")


def test_a_dictionary_with_no_frequency_still_yields_a_distribution(indicdict):
    """The fixtures and the no_frequency arm both need one; it must not divide by zero."""
    words = WordDistribution.train(indicdict)
    total = sum(10 ** words.log10_probability(e) for e in indicdict.entries.values())
    assert total == pytest.approx(1.0)


# -- the priors ------------------------------------------------------------


def test_the_segment_prior_is_a_truncated_renormalised_geometric(grammar):
    values = [10 ** grammar.log10_structure(k) for k in range(1, 6)]
    assert sum(values) == pytest.approx(1.0)
    for first, second in pairwise(values):
        assert second == pytest.approx(first * 0.5)


def test_the_segment_prior_stops_at_max_segments(grammar):
    assert grammar.log10_structure(6) == -math.inf
    assert grammar.log10_structure(0) == -math.inf


def test_the_default_category_prior_is_uniform(grammar):
    """Uniform is the maximum-entropy choice with no password corpus to fit."""
    values = [10 ** grammar.log10_category(name) for name in PCFG_CATEGORIES]
    assert sum(values) == pytest.approx(1.0)
    assert all(value == pytest.approx(1 / len(PCFG_CATEGORIES)) for value in values)


def test_a_configured_category_prior_is_renormalised(ranked_indicdict):
    settings = GrammarSettings.from_config(
        {"grammar": {"ngram_order": 3, "category_prior": {"word": 3.0, "digits": 1.0}}},
        SCORING,
    )
    grammar = PcfgGrammar.train(ranked_indicdict, settings)
    assert 10 ** grammar.log10_category(CATEGORY_WORD) == pytest.approx(0.75)
    assert 10 ** grammar.log10_category(CATEGORY_DIGITS) == pytest.approx(0.25)
    assert grammar.log10_category(CATEGORY_UNKNOWN) == -math.inf


def test_a_category_prior_naming_an_unknown_category_is_refused(ranked_indicdict):
    settings = GrammarSettings.from_config(
        {"grammar": {"category_prior": {"leetspeak": 1.0}}}, SCORING
    )
    with pytest.raises(ValueError, match="unknown categories"):
        PcfgGrammar.train(ranked_indicdict, settings)


def test_a_geometric_decay_outside_zero_to_one_is_refused(ranked_indicdict):
    settings = GrammarSettings.from_config({"grammar": {"segment_continuation": 1.5}}, SCORING)
    with pytest.raises(ValueError, match="geometric decay"):
        PcfgGrammar.train(ranked_indicdict, settings)


# -- terminals -------------------------------------------------------------


def test_digit_terminals_sum_to_one_over_every_run(grammar):
    total = 0.0
    for length in range(1, grammar.settings.max_run_length + 1):
        total += 10 ** grammar.log10_digits("1" * length) * 10**length
    assert total == pytest.approx(1.0)


def test_symbol_terminals_sum_to_one_over_every_run(grammar):
    total = 0.0
    for length in range(1, grammar.settings.max_run_length + 1):
        total += 10 ** grammar.log10_symbols("!" * length) * 33**length
    assert total == pytest.approx(1.0)


def test_the_year_terminal_enumerates_the_window(grammar):
    assert 10 ** grammar.log10_year() == pytest.approx(1 / 136)


def test_a_word_not_in_the_dictionary_has_no_word_terminal(grammar):
    log10, entry = grammar.log10_word("zzzzzz")
    assert log10 == -math.inf
    assert entry is None


def test_a_run_longer_than_the_limit_has_no_terminal(grammar):
    assert grammar.log10_unknown("a" * 40) == -math.inf
    assert grammar.log10_digits("1" * 40) == -math.inf


# -- the parser ------------------------------------------------------------


def test_a_dictionary_word_derives_through_the_word_category(grammar):
    derivation = best_derivation(grammar, "bharat")
    assert derivation.structure == (CATEGORY_WORD,)
    assert derivation.supported


def test_a_word_and_a_year_derive_as_two_segments(grammar):
    derivation = best_derivation(grammar, "bharat2024")
    assert derivation.structure == (CATEGORY_WORD, CATEGORY_YEAR)


def test_a_four_digit_run_outside_the_window_is_not_a_year(grammar):
    derivation = best_derivation(grammar, "bharat1234")
    assert CATEGORY_YEAR not in derivation.structure
    assert CATEGORY_DIGITS in derivation.structure


def test_a_symbol_run_derives_through_the_symbol_category(grammar):
    derivation = best_derivation(grammar, "bharat@")
    assert derivation.structure == (CATEGORY_WORD, CATEGORY_SYMBOLS)


def test_two_dictionary_words_derive_as_two_word_segments(grammar):
    derivation = best_derivation(grammar, "merabharat")
    assert derivation.structure == (CATEGORY_WORD, CATEGORY_WORD)


def test_an_unknown_spelling_falls_back_to_the_character_model(grammar):
    derivation = best_derivation(grammar, "bhagwaan")
    assert derivation.structure == (CATEGORY_UNKNOWN,)
    assert derivation.supported


def test_the_derivation_covers_the_whole_password(grammar):
    for password in ("bharat2024", "mera@123", "bhagwaan", "bharat"):
        derivation = best_derivation(grammar, password)
        assert derivation.segments[0].start == 0
        assert derivation.segments[-1].end == len(password)
        for left, right in zip(derivation.segments, derivation.segments[1:], strict=False):
            assert left.end == right.start


def test_the_derivation_probability_is_the_sum_of_its_parts(grammar):
    """No hidden term. What the parser reports is what the segments and the
    structure prior add up to -- which is what makes a derivation auditable."""
    derivation = best_derivation(grammar, "bharat2024")
    total = derivation.log10_structure + sum(
        segment.log10_probability for segment in derivation.segments
    )
    assert derivation.log10_probability == pytest.approx(total)


def test_a_password_needing_more_segments_than_allowed_is_unsupported(ranked_indicdict):
    settings = GrammarSettings.from_config({"grammar": {"max_segments": 2}}, SCORING)
    grammar = PcfgGrammar.train(ranked_indicdict, settings)
    derivation = best_derivation(grammar, "a1b2c3d4e5")
    assert not derivation.supported
    assert derivation.log10_probability == -math.inf


def test_an_empty_password_is_unsupported_rather_than_certain(grammar):
    derivation = best_derivation(grammar, "")
    assert not derivation.supported
    assert derivation.segments == ()


def test_the_parse_is_deterministic(grammar):
    first = best_derivation(grammar, "merabharat2024")
    second = best_derivation(grammar, "merabharat2024")
    assert first.structure == second.structure
    assert first.log10_probability == second.log10_probability


def test_a_segment_describes_itself_without_the_token(grammar):
    """The redaction rule, enforced at the type rather than at serialisation."""
    derivation = best_derivation(grammar, "bharat2024")
    for segment in derivation.segments:
        described = segment.describe()
        assert "token" not in described
        assert "native_form" not in described
        assert segment.token not in str(described)


def test_a_segment_can_be_asked_for_its_token_explicitly(grammar):
    derivation = best_derivation(grammar, "bharat")
    described = derivation.segments[0].describe(include_token=True)
    assert described["token"] == "bharat"


def test_capitalisation_lowers_probability_by_exactly_one_factor_of_two(grammar):
    lower = best_derivation(grammar, "bharat").log10_probability
    upper = best_derivation(grammar, "Bharat").log10_probability
    assert lower - upper == pytest.approx(math.log10(2))


def test_the_grammar_is_deterministic_across_two_trainings(ranked_indicdict, settings):
    first = PcfgGrammar.train(ranked_indicdict, settings)
    second = PcfgGrammar.train(ranked_indicdict, settings)
    for password in ("bharat", "bharat2024", "bhagwaan", "qxzjv"):
        assert best_derivation(first, password).log10_probability == pytest.approx(
            best_derivation(second, password).log10_probability
        )


def test_sampling_a_derivation_is_reproducible_from_a_seed(grammar):
    first = [grammar.sample_log10_probability(random.Random(9)) for _ in range(3)]
    second = [grammar.sample_log10_probability(random.Random(9)) for _ in range(3)]
    assert first == second


def test_a_sampled_derivation_never_reports_more_than_one_probability(grammar):
    rng = random.Random(2)
    for _ in range(200):
        log10, segments = grammar.sample_log10_probability(rng)
        assert log10 <= 0.0
        assert 1 <= segments <= grammar.settings.max_segments
