"""The comparison statistics, and the rule that no password survives them."""

from __future__ import annotations

import json

import pytest

from conftest import TIER_ORDER, build_meter, make_entry
from indicpass.password.benchmark import generate_corpus
from indicpass.password.dictionary import IndicDict
from indicpass.password.experiment import (
    AGREEMENT_TOLERANCE,
    SampleResult,
    aggregate,
    compare,
    compare_all,
    false_match_probe,
    overall,
    score_corpus,
)


def row(
    sample_id: str,
    category: str = "indic_word",
    *,
    log10: float,
    baseline: float | None = None,
    score: int = 2,
    baseline_score: int | None = 2,
    matches: int = 0,
    ranked: int = 0,
) -> SampleResult:
    return SampleResult(
        sample_id=sample_id,
        category=category,
        length=8,
        construction="test",
        log10_guesses=log10,
        score=score,
        indic_matches=matches,
        ranked_matches=ranked,
        baseline_log10_guesses=baseline,
        baseline_score=baseline_score if baseline is not None else None,
    )


# -- aggregation -----------------------------------------------------------


def test_aggregation_reports_both_a_mean_and_a_median():
    """Guess counts span thirty orders of magnitude; either alone misleads."""
    rows = [row(f"a-{i}", log10=value) for i, value in enumerate([1.0, 2.0, 3.0, 40.0])]
    stats = aggregate(rows, "indic_word")

    assert stats.samples == 4
    assert stats.mean_log10_guesses == 11.5
    assert stats.median_log10_guesses == 2.5


def test_match_rates_count_samples_not_matches():
    rows = [
        row("a-1", log10=5.0, matches=3, ranked=2),
        row("a-2", log10=5.0, matches=0, ranked=0),
    ]
    stats = aggregate(rows, "indic_word")
    assert stats.match_rate == 0.5
    assert stats.ranked_match_rate == 0.5


def test_an_empty_category_does_not_divide_by_zero():
    assert aggregate([], "indic_word").samples == 0


def test_the_score_distribution_is_carried_for_every_band():
    rows = [row("a-1", log10=1.0, score=0), row("a-2", log10=9.0, score=4)]
    assert aggregate(rows, "indic_word").score_distribution == {0: 1, 4: 1}


# -- comparison ------------------------------------------------------------


def test_lower_means_indicpass_estimated_fewer_guesses():
    rows = [
        row("a-1", log10=3.0, baseline=5.0),  # IndicPass found it weaker
        row("a-2", log10=7.0, baseline=5.0),  # and stronger
        row("a-3", log10=5.0, baseline=5.0),  # and agreed
    ]
    result = compare(rows, "indic_word")

    assert (result.lower, result.higher, result.equal) == (1, 1, 1)
    assert result.mean_difference == pytest.approx(0.0)
    assert result.median_difference == 0.0


def test_estimates_within_the_tolerance_count_as_agreeing():
    """Below the tolerance the gap is smaller than either estimator's modelling
    error, so naming a winner would be reporting noise."""
    rows = [row("a-1", log10=5.0 + AGREEMENT_TOLERANCE / 2, baseline=5.0)]
    assert compare(rows, "indic_word").equal == 1


def test_a_missing_baseline_is_an_error_not_a_blank_column():
    """A comparison table with a hole in it is worse than no table."""
    with pytest.raises(ValueError, match="no baseline estimate"):
        compare([row("a-1", log10=5.0, baseline=None)], "indic_word")


def test_the_combined_estimate_is_the_cheaper_of_the_two():
    """An attacker holds every wordlist they can get, and guessing is a minimum."""
    rows = [row("a-1", log10=3.0, baseline=5.0), row("a-2", log10=8.0, baseline=6.0)]
    result = compare(rows, "indic_word")

    assert result.combined_mean_log10_guesses == pytest.approx((3.0 + 6.0) / 2)
    # Only the first sample gained anything: -2 on one of two rows.
    assert result.mean_information_added == pytest.approx(-1.0)


def test_information_added_is_never_positive():
    """A minimum cannot exceed either of its arguments. If this ever fails, the
    combined estimator is inventing strength, not finding weakness."""
    rows = [row(f"a-{i}", log10=float(i), baseline=5.0) for i in range(1, 10)]
    assert compare(rows, "indic_word").mean_information_added <= 0.0


def test_information_added_is_zero_when_the_baseline_already_knew():
    rows = [row("a-1", log10=9.0, baseline=4.0), row("a-2", log10=8.0, baseline=4.0)]
    result = compare(rows, "indic_word")
    assert result.mean_information_added == 0.0
    assert result.lower == 0


def test_score_disagreements_are_counted_separately_from_guesses():
    rows = [
        row("a-1", log10=3.0, baseline=5.0, score=1, baseline_score=3),
        row("a-2", log10=5.0, baseline=5.0, score=2, baseline_score=2),
    ]
    result = compare(rows, "indic_word")
    assert result.score_disagreements == 1
    assert result.mean_score_difference == -1.0


def test_categories_come_back_in_the_canonical_order():
    rows = [
        row("r-1", "random", log10=11.0, baseline=11.0),
        row("e-1", "english", log10=4.0, baseline=4.0),
    ]
    assert [c.category for c in compare_all(rows)] == ["english", "random"]


def test_the_overall_figure_labels_itself_as_nearly_meaningless():
    rows = [row("a-1", log10=3.0), row("r-1", "random", log10=11.0)]
    described = overall(rows)
    assert described["samples"] == 2
    assert "per-category" in described["note"]


# -- nothing leaks ---------------------------------------------------------


def test_a_scored_row_keeps_the_identity_and_drops_the_password(meter_with_baseline):
    corpus = generate_corpus(seed=42, samples_per_category=8)
    results = score_corpus(meter_with_baseline, corpus)

    text = json.dumps([r.to_dict() for r in results], ensure_ascii=False)
    for sample in corpus:
        assert sample.password not in text
    assert {r.sample_id for r in results} == {s.sample_id for s in corpus}


def test_a_scored_row_carries_both_estimates(meter_with_baseline):
    corpus = generate_corpus(seed=42, samples_per_category=4)
    for result in score_corpus(meter_with_baseline, corpus):
        assert result.baseline_log10_guesses is not None
        assert result.baseline_score is not None


def test_a_row_without_a_baseline_omits_the_columns_entirely(meter):
    """Absent, not zero -- a zero would read as "the baseline said nothing"."""
    corpus = generate_corpus(seed=42, samples_per_category=2)
    payload = score_corpus(meter, corpus)[0].to_dict()
    assert "baseline_log10_guesses" not in payload
    assert "baseline_score" not in payload


# -- false matches on random controls --------------------------------------


LETTERS = "abcdefghijklmnopqrstuvwxyz"


@pytest.fixture(scope="module")
def _stuffed_entries():
    """Every three-letter string, i.e. the worst case the real dictionary is a
    40% sample of. Built once; it is 17,576 entries."""
    return [
        make_entry(a + b + c, tier="mined", source="IndicCorp")
        for a in LETTERS
        for b in LETTERS
        for c in LETTERS
    ]


@pytest.fixture
def stuffed_meter(_stuffed_entries, matcher_settings, scoring_settings, scale):
    dictionary = IndicDict.from_entries(
        _stuffed_entries, language="hin", tier_order=TIER_ORDER
    )
    return build_meter(dictionary, matcher_settings, scoring_settings, scale)


def test_the_false_match_probe_is_deterministic(stuffed_meter):
    """The figure quoted in a report has to be reproducible from its seed.

    Reproducibility is asserted; seed-*sensitivity* is not, because it is not
    observable through these aggregates -- with every three-letter string in the
    dictionary, an 8-character string offers exactly six spans whatever it says.
    The risk this guards against is a seed that does not survive a process
    boundary, which is why the generator is seeded from a string rather than
    from a tuple's salted ``hash()``.
    """
    kwargs = {"samples": 40, "lengths": (8,), "alphabets": {"lower": LETTERS}}
    first = false_match_probe(stuffed_meter, seed=7, **kwargs)
    assert false_match_probe(stuffed_meter, seed=7, **kwargs)["rows"] == first["rows"]


def test_the_probe_separates_offered_matches_from_accepted_ones(stuffed_meter):
    """The distinction the whole measurement exists for.

    A dictionary holding every three-letter string offers a match inside almost
    any text. What matters is whether one survives into the winning
    segmentation, because only then does the estimate rest on it.
    """
    probe = false_match_probe(
        stuffed_meter, seed=42, samples=60, lengths=(10,), alphabets={"lower": LETTERS}
    )
    row = probe["rows"][0]

    assert row["offered_rate"] == 1.0  # every string contains some 3-letter key
    assert row["accepted_rate"] < 0.2  # and the search throws nearly all of them out
    assert probe["worst_accepted_rate"] == row["accepted_rate"]


def test_the_probe_sweeps_every_requested_cell(meter):
    probe = false_match_probe(
        meter, seed=1, samples=5, lengths=(6, 8), alphabets={"a": "ab", "b": "cd"}
    )
    assert {(r["alphabet"], r["length"]) for r in probe["rows"]} == {
        ("a", 6), ("a", 8), ("b", 6), ("b", 8)
    }
    assert all(row["samples"] == 5 for row in probe["rows"])


def test_a_dictionary_free_meter_never_false_matches(matcher_settings, scoring_settings,
                                                     scale):
    empty = build_meter(
        IndicDict.from_entries([], language="hin", tier_order=TIER_ORDER),
        matcher_settings,
        scoring_settings,
        scale,
    )
    probe = false_match_probe(empty, seed=42, samples=30, lengths=(10,))
    assert probe["worst_accepted_rate"] == 0.0
