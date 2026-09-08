"""The PCFG inside the meter, the result schema, the config, and the reports.

Milestone 3 adds an estimator; it must not move one. The point of most of these
tests is what *has not* changed: `guess_number` is still the Milestone 2
number, `to_dict()` still carries every field it did, and a meter with no
grammar attached behaves exactly as before.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import build_meter
from indicpass.config import load_config
from indicpass.password.experiment import (
    ESTIMATORS,
    SampleResult,
    compare_estimators,
    pcfg_structure_census,
    score_corpus,
    shadow_rows,
)
from indicpass.password.meter import describe_pcfg
from indicpass.password.pcfg.estimator import EstimatorSettings, PcfgEstimator
from indicpass.password.pcfg.grammar import GrammarSettings, PcfgGrammar
from indicpass.password.pcfg.probe import TARGETED_CASES

SCORING = {
    "year_range": (1900, 2035),
    "digits_per_position": 10,
    "symbol_alphabet_size": 33,
    "bruteforce_cardinality": 10,
    "character_class_sizes": {"lowercase": 26, "uppercase": 26, "digits": 10, "symbols": 33},
}
PCFG_CONFIG = {
    "grammar": {"ngram_order": 3, "max_segments": 6, "max_run_length": 12},
    "estimator": {"samples": 6000, "sample_seed": 42, "curve_points": 300},
}


@pytest.fixture
def pcfg(ranked_indicdict, scale) -> PcfgEstimator:
    grammar = PcfgGrammar.train(
        ranked_indicdict, GrammarSettings.from_config(PCFG_CONFIG, SCORING)
    )
    return PcfgEstimator.train(
        grammar, settings=EstimatorSettings.from_config(PCFG_CONFIG, SCORING), scale=scale
    )


@pytest.fixture
def pcfg_meter(ranked_indicdict, matcher_settings, scoring_settings, scale, pcfg):
    return build_meter(ranked_indicdict, matcher_settings, scoring_settings, scale, pcfg=pcfg)


# -- the meter -------------------------------------------------------------


def test_a_meter_without_a_grammar_reports_none(ranked_meter):
    result = ranked_meter.score("bharat2024")
    assert result.pcfg is None
    assert result.pcfg_log10_guesses is None
    assert describe_pcfg(ranked_meter) is None


def test_attaching_a_grammar_does_not_change_the_primary_estimate(
    ranked_meter, pcfg_meter
):
    """The load-bearing back-compatibility test.

    Adding a model to the meter must not silently move the number Milestone 2's
    reports were produced with, or the two milestones would not be comparable.
    """
    for password in ("bharat", "bharat2024", "mera@123", "kqzjxwvbnr"):
        assert (
            pcfg_meter.score(password).log10_guesses
            == ranked_meter.score(password).log10_guesses
        )
        assert (
            pcfg_meter.score(password).strength_score
            == ranked_meter.score(password).strength_score
        )


def test_the_grammar_reports_alongside_the_meter(pcfg_meter):
    result = pcfg_meter.score("bharat2024")
    assert result.pcfg is not None
    assert result.pcfg.structure == ("word", "year")
    assert result.pcfg_log10_guesses == result.pcfg.log10_guesses


def test_the_combined_estimate_is_the_minimum_of_everything_that_ran(
    meter_with_baseline, pcfg_meter, ranked_meter
):
    result = pcfg_meter.score("bharat2024")
    assert result.combined_log10_guesses == min(
        result.log10_guesses, result.pcfg.log10_guesses
    )
    # With nothing else attached the combination is just the meter's own number.
    assert ranked_meter.score("bharat").combined_log10_guesses == pytest.approx(
        ranked_meter.score("bharat").log10_guesses
    )


def test_describe_pcfg_names_what_produced_the_numbers(pcfg_meter):
    described = describe_pcfg(pcfg_meter)
    assert described["name"] == "pcfg"
    assert described["grammar"]["settings"]["ngram_order"] == 3
    assert described["curve"]["samples"] > 0


# -- the result schema -----------------------------------------------------


def test_the_serialised_result_keeps_every_milestone_two_field(ranked_meter, pcfg_meter):
    """A field the previous milestone's reports read must not disappear."""
    before = ranked_meter.score("bharat2024").to_dict()
    after = pcfg_meter.score("bharat2024").to_dict()
    assert set(before) <= set(after)
    for key, value in before.items():
        assert after[key] == value, key


def test_the_pcfg_block_is_nested_and_never_flattened(pcfg_meter):
    """A reader must not be able to mistake the grammar's number for the meter's."""
    payload = pcfg_meter.score("bharat2024").to_dict()
    assert payload["pcfg"]["log10_guesses"] != payload["log10_guesses"]
    assert payload["guess_number"] == payload["indicpass_guesses"]


def test_no_pcfg_block_appears_when_no_grammar_ran(ranked_meter):
    payload = ranked_meter.score("bharat2024").to_dict()
    assert "pcfg" not in payload
    assert "combined_log10_guesses" not in payload


def test_the_serialised_result_still_redacts_the_password(pcfg_meter):
    payload = pcfg_meter.score("merabharat2024").to_dict()
    text = json.dumps(payload, ensure_ascii=False)
    for piece in ("merabharat2024", "merabharat", "bharat", "mera", "2024"):
        assert piece not in text


def test_the_grammar_cannot_leak_a_token_through_the_meter(pcfg_meter):
    """`include_tokens=True` is for the terminal, and it must not reach the parse."""
    payload = pcfg_meter.score("bharat2024").to_dict(include_tokens=True)
    for segment in payload["pcfg"]["segments"]:
        assert "token" not in segment
        assert "native_form" not in segment


# -- the experiment plumbing ----------------------------------------------


def test_every_named_estimator_has_a_column():
    row = SampleResult(
        sample_id="x-0001", category="indic_word", length=6, construction="indic/lower",
        log10_guesses=4.0, score=1, indic_matches=1, ranked_matches=1,
        baseline_log10_guesses=4.5, baseline_score=1,
        pcfg_log10_guesses=5.0, pcfg_score=1,
    )
    assert {row.column(name) for name in ESTIMATORS} == {4.0, 4.5, 5.0}


def test_an_unknown_estimator_is_refused():
    row = SampleResult("x-1", "random", 8, "random", 8.0, 3, 0, 0)
    with pytest.raises(ValueError, match="Unknown estimator"):
        row.column("astrology")


def test_shadow_rows_zero_the_match_counts_that_do_not_apply():
    """A match count belongs to the Milestone 2 matcher; carrying it across
    another estimator's rows would publish a number about the wrong model."""
    rows = [
        SampleResult("a-1", "indic_word", 6, "indic/lower", 4.0, 1, 2, 2,
                     pcfg_log10_guesses=5.0, pcfg_score=1)
    ]
    shadowed = shadow_rows(rows, "pcfg")
    assert shadowed[0].log10_guesses == 5.0
    assert shadowed[0].indic_matches == 0


def test_scoring_a_corpus_carries_the_pcfg_columns(pcfg_meter):
    from indicpass.password.benchmark import generate_corpus

    corpus = generate_corpus(seed=42, samples_per_category=3, categories=["indic_word"])
    rows = score_corpus(pcfg_meter, corpus)
    assert all(row.pcfg_log10_guesses is not None for row in rows)
    assert all(row.pcfg_structure for row in rows)


def test_a_sample_row_still_carries_no_password(pcfg_meter):
    from indicpass.password.benchmark import generate_corpus

    corpus = generate_corpus(seed=42, samples_per_category=5)
    rows = score_corpus(pcfg_meter, corpus)
    text = json.dumps([row.to_dict() for row in rows], ensure_ascii=False)
    for sample in corpus:
        assert sample.password not in text


def test_comparing_two_estimators_reports_the_information_added():
    rows = [
        SampleResult(f"i-{i}", "indic_word", 6, "indic/lower", 4.0, 1, 1, 1,
                     baseline_log10_guesses=5.0, baseline_score=2,
                     pcfg_log10_guesses=3.0, pcfg_score=1)
        for i in range(4)
    ]
    comparison = compare_estimators(rows, "indic_word", left="pcfg", right="baseline")
    assert comparison.mean_difference == pytest.approx(-2.0)
    assert comparison.improved == 4
    assert comparison.combined_mean_log10_guesses == pytest.approx(3.0)
    assert comparison.mean_information_added == pytest.approx(-2.0)


def test_information_added_is_never_positive():
    """It is a minimum minus one of its own arguments, so it cannot be."""
    rows = [
        SampleResult(f"i-{i}", "english", 8, "english/lower", 9.0, 3,
                     0, 0, baseline_log10_guesses=4.0, baseline_score=1,
                     pcfg_log10_guesses=9.0, pcfg_score=3)
        for i in range(3)
    ]
    comparison = compare_estimators(rows, "english", left="pcfg", right="baseline")
    assert comparison.mean_information_added == pytest.approx(0.0)


def test_a_missing_estimator_column_raises_rather_than_comparing_nothing():
    rows = [SampleResult("i-1", "random", 8, "random", 8.0, 3, 0, 0)]
    with pytest.raises(ValueError, match="no 'pcfg' estimate"):
        compare_estimators(rows, "random", left="pcfg", right="indicpass")


def test_the_structure_census_publishes_shape_and_never_content():
    rows = [
        SampleResult(f"i-{i}", "indic_year", 10, "indic+year/lower", 6.0, 2, 1, 1,
                     pcfg_log10_guesses=7.0, pcfg_score=2,
                     pcfg_structure="word+year", pcfg_word_segments=1,
                     pcfg_floor_applied=False, pcfg_supported=True)
        for i in range(5)
    ]
    census = pcfg_structure_census(rows, "indic_year")
    assert census["structures"][0]["structure"] == "word+year"
    assert census["word_segment_rate"] == 1.0
    assert census["floor_rate"] == 0.0
    assert census["unsupported_rate"] == 0.0


# -- configuration ---------------------------------------------------------


def test_the_shipped_config_declares_a_pcfg_section():
    section = load_config().password_section("pcfg")
    assert section["enabled"] is True
    assert "hin" in section["files"]


def test_the_shipped_grammar_settings_are_understood():
    config = load_config()
    settings = GrammarSettings.from_config(
        config.password_section("pcfg"), config.password_section("scoring")
    )
    assert settings.ngram_order >= 2
    assert 0.0 < settings.segment_continuation < 1.0
    assert settings.max_segments >= 2
    # Uniform by default: with no password corpus, maximum entropy is the only
    # choice that does not assert something unmeasured.
    assert settings.category_prior == {}
    assert settings.unranked_policy == "tier_coverage"


def test_the_shipped_estimator_settings_are_understood():
    config = load_config()
    settings = EstimatorSettings.from_config(
        config.password_section("pcfg"), config.password_section("scoring")
    )
    assert settings.samples >= 1000
    assert settings.curve_points >= 100
    # The floor is retained deliberately and is what keeps random controls in
    # line with the baseline; turning it off is an ablation arm, not a default.
    assert settings.bruteforce_floor is True


def test_the_pcfg_shares_the_brute_force_assumption_with_the_meter():
    """Two estimators that disagreed about brute force would repeat exactly the
    confound Milestone 2 measured and removed."""
    config = load_config()
    scoring = config.password_section("scoring")
    settings = EstimatorSettings.from_config(config.password_section("pcfg"), scoring)
    assert settings.bruteforce_cardinality == scoring["bruteforce_cardinality"]


# -- the committed artefact and reports ------------------------------------


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_the_committed_artefact_matches_the_committed_dictionary():
    """The fingerprint's whole job, checked against the real files."""
    from indicpass.password.dictionary import IndicDict
    from indicpass.password.pcfg.artifact import load_estimator
    from indicpass.password.scoring import StrengthScale

    config = load_config()
    dictionary_config = config.password_section("dictionary")
    path = config.resolve(dictionary_config["files"]["hin"])
    artefact = config.resolve(config.password_section("pcfg")["files"]["hin"])
    if not path.is_file() or not artefact.is_file():  # pragma: no cover
        pytest.skip("Dictionary or PCFG artefact not built in this checkout.")

    tier_order = [str(tier["name"]) for tier in dictionary_config["tiers"]]
    dictionary = IndicDict.load(path, language="hin", tier_order=tier_order)
    estimator = load_estimator(
        artefact,
        dictionary=dictionary,
        scale=StrengthScale.from_config(config.password_section("strength")),
        scoring=config.password_section("scoring"),
    )
    assert estimator.curve.samples > 0


def test_no_probe_password_appears_in_any_committed_report():
    """The targeted cases are committed source; a report pairing one with an id
    is not."""
    reports = _root() / "results" / "reports"
    files = sorted(reports.glob("pcfg_*.md")) + sorted(reports.glob("pcfg_*.json"))
    if not files:  # pragma: no cover - a fresh checkout before any run
        pytest.skip("No PCFG reports generated yet; run scripts/pcfg_benchmark.py")

    for path in files:
        text = path.read_text(encoding="utf-8")
        for case in TARGETED_CASES:
            assert case.password not in text, f"{path.name}: {case.case_id}"


def test_no_committed_pcfg_report_maps_a_sample_id_to_a_password():
    from indicpass.password.benchmark import generate_corpus

    reports = _root() / "results" / "reports"
    files = sorted(reports.glob("pcfg_*.md")) + sorted(reports.glob("pcfg_*.json"))
    if not files:  # pragma: no cover
        pytest.skip("No PCFG reports generated yet; run scripts/pcfg_benchmark.py")

    corpus = generate_corpus(seed=42, samples_per_category=200)
    for path in files:
        text = path.read_text(encoding="utf-8")
        for sample in corpus:
            if sample.sample_id not in text:
                continue
            index = text.index(sample.sample_id)
            window = text[max(0, index - 200) : index + 400]
            assert sample.password not in window, f"{path.name}: {sample.sample_id}"


def test_the_committed_benchmark_reports_a_clean_random_control():
    """The finding every Indic claim in this milestone depends on.

    Pinned against the real report rather than a fixture: a grammar that priced
    random strings below enumerating them would make the Indic effect an
    artefact of the same mechanism, and that must fail loudly if it ever changes.
    """
    path = _root() / "results" / "reports" / "pcfg_benchmark_hin.json"
    if not path.is_file():  # pragma: no cover
        pytest.skip("No PCFG benchmark report; run scripts/pcfg_benchmark.py")

    report = json.loads(path.read_text(encoding="utf-8"))
    control = report["random_control"]
    assert control["worst_below_bruteforce_rate"] <= 0.02
    random_row = next(
        row for row in report["pcfg_vs_baseline"] if row["category"] == "random"
    )
    assert abs(random_row["mean_information_added"]) <= 0.05
