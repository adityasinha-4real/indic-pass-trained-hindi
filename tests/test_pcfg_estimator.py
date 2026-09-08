"""The guess curve, the estimate, the artefact, and the random control.

The curve is where a probability becomes a guess number, which is the step that
makes the whole milestone more than a second scoring heuristic. So the tests
here check the estimator's *properties* -- unbiasedness in the small case,
monotonicity, the ``G <= 1/P`` bound, determinism -- rather than pinning
numbers that would only record what the code did on the day it was written.
"""

from __future__ import annotations

import json
import math

import pytest

from indicpass.password.pcfg.artifact import (
    ARTIFACT_VERSION,
    PcfgArtifactError,
    dictionary_fingerprint,
    load_estimator,
    save_estimator,
)
from indicpass.password.pcfg.estimator import (
    EstimatorSettings,
    GuessCurve,
    PcfgEstimator,
    log10_add,
)
from indicpass.password.pcfg.grammar import GrammarSettings, PcfgGrammar
from indicpass.password.pcfg.probe import (
    TARGETED_CASES,
    random_control_probe,
    score_targeted_cases,
)

SCORING = {
    "year_range": (1900, 2035),
    "digits_per_position": 10,
    "symbol_alphabet_size": 33,
    "bruteforce_cardinality": 10,
    "character_class_sizes": {"lowercase": 26, "uppercase": 26, "digits": 10, "symbols": 33},
}

PCFG_CONFIG = {
    "grammar": {"ngram_order": 3, "max_segments": 6, "max_run_length": 12},
    "estimator": {"samples": 8000, "sample_seed": 42, "curve_points": 400},
}


@pytest.fixture
def grammar(ranked_indicdict) -> PcfgGrammar:
    return PcfgGrammar.train(ranked_indicdict, GrammarSettings.from_config(PCFG_CONFIG, SCORING))


@pytest.fixture
def estimator_settings() -> EstimatorSettings:
    return EstimatorSettings.from_config(PCFG_CONFIG, SCORING)


@pytest.fixture
def estimator(grammar, estimator_settings, scale) -> PcfgEstimator:
    return PcfgEstimator.train(grammar, settings=estimator_settings, scale=scale)


# -- the log-space helper --------------------------------------------------


def test_log10_add_matches_the_direct_computation():
    assert log10_add(2.0, 2.0) == pytest.approx(math.log10(200))
    assert log10_add(3.0, 0.0) == pytest.approx(math.log10(1001))


def test_log10_add_survives_magnitudes_no_float_could_hold():
    """The curve accumulates 1/p over the tail, where p is 10**-90."""
    assert log10_add(400.0, 399.0) == pytest.approx(400 + math.log10(1.1))
    assert log10_add(-math.inf, 5.0) == 5.0


# -- the guess curve -------------------------------------------------------


def test_the_curve_is_monotone_in_both_axes(estimator):
    """A less probable password can never be reached sooner."""
    curve = estimator.curve
    for first, second in zip(
        curve.log10_probabilities, curve.log10_probabilities[1:], strict=False
    ):
        assert second <= first
    for first, second in zip(curve.log10_guesses, curve.log10_guesses[1:], strict=False):
        assert second >= first


def test_a_less_probable_password_never_costs_fewer_guesses(estimator):
    curve = estimator.curve
    previous = -1.0
    for log10_probability in (-1.0, -3.0, -6.0, -12.0, -25.0, -60.0):
        value = curve.log10_guesses_for(log10_probability)
        assert value >= previous
        previous = value


def test_the_estimate_never_exceeds_one_over_the_probability(estimator):
    """``G <= 1/P`` is exact: at most 1/p passwords can have probability >= p.

    Checked across the whole range including the extrapolated tail, because the
    bound is what makes the extrapolation safe.
    """
    for log10_probability in (-0.5, -2.0, -5.0, -11.0, -30.0, -80.0, -200.0):
        assert estimator.curve.log10_guesses_for(log10_probability) <= -log10_probability + 1e-9


def test_the_estimate_is_never_below_one_guess(estimator):
    assert estimator.curve.log10_guesses_for(0.0) >= 0.0
    assert estimator.curve.log10_guesses_for(-0.001) >= 0.0


def test_an_impossible_derivation_costs_infinitely_many_guesses(estimator):
    assert estimator.curve.log10_guesses_for(-math.inf) == math.inf


def test_the_curve_reproduces_from_its_seed(grammar, estimator_settings):
    first = GuessCurve.build(grammar, samples=4000, seed=17, curve_points=200)
    second = GuessCurve.build(grammar, samples=4000, seed=17, curve_points=200)
    assert first.log10_probabilities == second.log10_probabilities
    assert first.log10_guesses == second.log10_guesses


def test_a_different_seed_gives_a_different_curve(grammar):
    first = GuessCurve.build(grammar, samples=4000, seed=1, curve_points=200)
    second = GuessCurve.build(grammar, samples=4000, seed=2, curve_points=200)
    assert first.log10_probabilities != second.log10_probabilities


def test_two_seeds_agree_on_where_a_password_lands(grammar):
    """Sampling noise must be small next to the effects the reports discuss.

    If re-seeding moved an estimate by an order of magnitude, no per-category
    difference in the benchmark would mean anything.
    """
    first = GuessCurve.build(grammar, samples=20000, seed=1, curve_points=800)
    second = GuessCurve.build(grammar, samples=20000, seed=2, curve_points=800)
    for log10_probability in (-3.0, -5.0, -8.0, -12.0):
        assert first.log10_guesses_for(log10_probability) == pytest.approx(
            second.log10_guesses_for(log10_probability), abs=0.5
        )


def test_the_curve_estimates_a_known_count_on_a_grammar_it_can_enumerate(scale):
    """The estimator's correctness, checked against a distribution with an exact answer.

    A grammar restricted to single digit-runs of length 1 generates exactly ten
    equiprobable passwords, so every one of them has guess number 10. The
    Monte-Carlo estimator must find that without being told.
    """
    from conftest import TIER_ORDER
    from indicpass.password.dictionary import IndicDict

    empty = IndicDict.from_entries([], language="hin", tier_order=TIER_ORDER)
    settings = GrammarSettings.from_config(
        {
            "grammar": {
                "max_segments": 1,
                "max_run_length": 1,
                "category_prior": {"digits": 1.0},
            }
        },
        SCORING,
    )
    grammar = PcfgGrammar.train(empty, settings)
    curve = GuessCurve.build(grammar, samples=20000, seed=42, curve_points=200)

    # Every one of the ten passwords has probability 1/10.
    assert curve.log10_guesses_for(math.log10(0.1)) == pytest.approx(1.0, abs=0.05)


def test_the_curve_round_trips_through_json(estimator):
    restored = GuessCurve.from_dict(json.loads(json.dumps(estimator.curve.to_dict())))
    # Serialised to six decimals: enough that a probe lands in the same place,
    # and small enough that a diff of the committed artefact stays readable.
    assert restored.log10_probabilities == pytest.approx(
        estimator.curve.log10_probabilities, abs=1e-6
    )
    assert restored.log10_guesses == pytest.approx(estimator.curve.log10_guesses, abs=1e-6)
    assert restored.tail_slope == pytest.approx(estimator.curve.tail_slope, abs=1e-6)
    for probe in (-3.0, -8.0, -20.0):
        assert restored.log10_guesses_for(probe) == pytest.approx(
            estimator.curve.log10_guesses_for(probe), abs=1e-4
        )


def test_a_curve_needs_more_than_one_sample(grammar):
    with pytest.raises(ValueError, match="at least 2 samples"):
        GuessCurve.build(grammar, samples=1, seed=42)


# -- the estimate ----------------------------------------------------------


def test_a_known_word_is_cheaper_than_an_unknown_one(estimator):
    assert estimator.estimate("bharat").log10_guesses < estimator.estimate(
        "bhagwaan"
    ).log10_guesses


def test_adding_a_year_makes_a_password_more_expensive(estimator):
    assert (
        estimator.estimate("bharat2024").log10_guesses
        > estimator.estimate("bharat").log10_guesses
    )


def test_capitalising_costs_about_a_factor_of_two_not_orders_of_magnitude(estimator):
    lower = estimator.estimate("bharat").log10_guesses
    upper = estimator.estimate("Bharat").log10_guesses
    assert upper >= lower
    assert upper - lower < 1.0


def test_the_estimate_carries_its_derivation(estimator):
    estimate = estimator.estimate("bharat2024")
    assert estimate.structure == ("word", "year")
    assert len(estimate.segments) == 2
    assert estimate.log10_probability < 0


def test_the_estimate_never_writes_the_password_down(estimator):
    estimate = estimator.estimate("bharat2024")
    text = json.dumps(estimate.to_dict(), ensure_ascii=False)
    for piece in ("bharat", "2024", "bharat2024"):
        assert piece not in text


def test_the_brute_force_floor_is_reported_separately_from_the_grammar(estimator):
    """The floor is not a production of the grammar and must not look like one."""
    estimate = estimator.estimate("qxzjvwkpmr")
    assert estimate.grammar_log10_guesses > estimate.bruteforce_log10_guesses
    assert estimate.log10_guesses == pytest.approx(estimate.bruteforce_log10_guesses)
    assert estimate.floor_applied


def test_the_floor_can_be_turned_off_and_then_the_grammar_stands_alone(
    grammar, estimator_settings, scale
):
    import dataclasses

    bare = PcfgEstimator.train(
        grammar,
        settings=dataclasses.replace(estimator_settings, bruteforce_floor=False),
        scale=scale,
    )
    estimate = bare.estimate("qxzjvwkpmr")
    assert not estimate.floor_applied
    assert estimate.log10_guesses == pytest.approx(estimate.grammar_log10_guesses)


def test_an_unsupported_password_is_priced_by_the_floor_not_by_infinity(estimator):
    """`inf` would read as 'unbreakable'; it means 'this model says nothing'."""
    estimate = estimator.estimate("a1b2c3d4e5f6g7h8")
    assert not estimate.supported
    assert estimate.log10_guesses == pytest.approx(estimate.bruteforce_log10_guesses)
    assert math.isfinite(estimate.log10_guesses)


def test_the_score_comes_from_the_shared_strength_scale(estimator, scale):
    estimate = estimator.estimate("bharat2024")
    assert estimate.score == scale.score(estimate.log10_guesses)
    assert estimate.label == scale.label(estimate.score)


def test_scoring_the_same_password_twice_gives_the_same_answer(estimator):
    first = estimator.estimate("merabharat123")
    second = estimator.estimate("merabharat123")
    assert first.to_dict() == second.to_dict()


# -- the artefact ----------------------------------------------------------


def test_the_artefact_round_trips(tmp_path, estimator, ranked_indicdict, scale):
    path = save_estimator(estimator, tmp_path / "pcfg_hin.json", language="hin")
    restored = load_estimator(
        path, dictionary=ranked_indicdict, scale=scale, scoring=SCORING
    )
    # Agreement to the curve's stored precision (six decimals), which is the
    # most a round trip through JSON can promise.
    for password in ("bharat", "bharat2024", "bhagwaan", "qxzjv"):
        assert restored.estimate(password).log10_guesses == pytest.approx(
            estimator.estimate(password).log10_guesses, abs=1e-4
        )


def test_the_artefact_holds_no_password(tmp_path, estimator):
    path = save_estimator(estimator, tmp_path / "pcfg_hin.json", language="hin")
    text = path.read_text(encoding="utf-8")
    # Every fixture spelling, and every probe case, must be absent.
    for word in ("namaste", "bharat", "krishna", "sharma", "pyaar", "jaihind"):
        assert word not in text
    for case in TARGETED_CASES:
        assert case.password not in text


def test_the_artefact_does_not_store_the_grammar(tmp_path, estimator):
    """It stores a fingerprint and refits instead -- see the module docstring."""
    path = save_estimator(estimator, tmp_path / "pcfg_hin.json", language="hin")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "counts" not in json.dumps(payload)
    assert payload["training"]["dictionary"]["fingerprint"].startswith("sha256:")
    assert payload["artifact_version"] == ARTIFACT_VERSION


def test_a_dictionary_the_artefact_was_not_trained_on_is_refused(
    tmp_path, estimator, indicdict, scale
):
    """A curve built for one lexicon and applied to another is a silently wrong number."""
    path = save_estimator(estimator, tmp_path / "pcfg_hin.json", language="hin")
    with pytest.raises(PcfgArtifactError, match="different dictionary"):
        load_estimator(path, dictionary=indicdict, scale=scale, scoring=SCORING)


def test_a_missing_artefact_says_how_to_build_one(tmp_path, ranked_indicdict, scale):
    with pytest.raises(PcfgArtifactError, match="train_pcfg"):
        load_estimator(
            tmp_path / "absent.json", dictionary=ranked_indicdict, scale=scale, scoring=SCORING
        )


def test_an_artefact_from_another_schema_version_is_refused(
    tmp_path, estimator, ranked_indicdict, scale
):
    path = save_estimator(estimator, tmp_path / "pcfg_hin.json", language="hin")
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["artifact_version"] = "0.1"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(PcfgArtifactError, match="artefact version"):
        load_estimator(path, dictionary=ranked_indicdict, scale=scale, scoring=SCORING)


def test_the_fingerprint_covers_what_the_grammar_reads(ranked_indicdict, indicdict):
    """Same spellings, different frequencies -- a different grammar, so a different print."""
    assert dictionary_fingerprint(ranked_indicdict) != dictionary_fingerprint(indicdict)
    assert dictionary_fingerprint(ranked_indicdict) == dictionary_fingerprint(ranked_indicdict)


# -- the random control ----------------------------------------------------


def test_the_random_control_is_deterministic(estimator):
    first = random_control_probe(estimator, seed=42, samples=25, lengths=(8,))
    second = random_control_probe(estimator, seed=42, samples=25, lengths=(8,))
    assert first["rows"] == second["rows"]


def test_the_grammar_does_not_price_random_strings_below_brute_force(estimator):
    """The control the whole milestone rests on.

    A grammar that read random strings as cheaper than enumerating them would be
    inventing structure, and every Indic result would have to be read as the
    same artefact. Checked on the fixture grammar; the real one is measured in
    results/reports/pcfg_benchmark_hin.md.
    """
    probe = random_control_probe(estimator, seed=42, samples=60, lengths=(8, 12))
    assert probe["worst_below_bruteforce_rate"] <= 0.05


def test_the_control_reports_both_offered_structure_and_its_effect(estimator):
    probe = random_control_probe(estimator, seed=42, samples=20, lengths=(10,))
    row = probe["rows"][0]
    assert set(row) >= {
        "word_rate",
        "below_bruteforce_rate",
        "mean_grammar_minus_bruteforce",
    }


# -- the targeted cases ----------------------------------------------------


def test_every_targeted_family_the_brief_names_is_covered():
    families = {case.family for case in TARGETED_CASES}
    assert families == {
        "single_indic_word",
        "indic_word_year",
        "indic_word_digits",
        "multiple_indic_words",
        "indic_and_english",
        "indic_and_symbols",
        "case_variation",
        "unseen_token",
        "random_string",
    }


def test_targeted_case_ids_are_unique():
    ids = [case.case_id for case in TARGETED_CASES]
    assert len(ids) == len(set(ids))


def test_a_targeted_row_carries_no_password(estimator):
    rows = score_targeted_cases(estimator)
    text = json.dumps(rows, ensure_ascii=False)
    for case in TARGETED_CASES:
        assert case.password not in text


def test_a_targeted_row_carries_the_derivation(estimator):
    rows = {row["case_id"]: row for row in score_targeted_cases(estimator)}
    assert rows["year-01"]["pcfg"]["structure"] == ["word", "year"]
    assert rows["single-01"]["pcfg"]["structure"] == ["word"]
