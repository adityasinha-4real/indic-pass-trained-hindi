"""The frequency source: what it returns, and what it refuses to invent."""

from __future__ import annotations

import pytest

from indicpass.password.frequency import (
    FrequencyLookup,
    FrequencySource,
    FrequencyUnavailable,
    load_frequency_lookup,
)

SOURCE = FrequencySource(
    provider="fixture",
    version="0",
    language="hi",
    wordlist="small",
    semantics="Zipf frequency of the native-script word",
    entries=3,
    license="n/a",
)


@pytest.fixture
def lookup() -> FrequencyLookup:
    return FrequencyLookup(
        source=SOURCE,
        table={"भारत": 6.38, "मेरा": 5.78, "प्यार": 5.68},
    )


# -- lookups ---------------------------------------------------------------


def test_a_known_native_form_returns_its_value_and_its_provenance(lookup):
    reading = lookup.lookup("भारत")
    assert reading.observed
    assert reading.value == 6.38
    assert reading.matched_via == "native_form"
    assert reading.source is SOURCE


def test_an_unknown_word_is_an_explicit_absence_not_a_zero(lookup):
    """Zero would be a claim: "this word never occurs". None is the truth."""
    reading = lookup.lookup("क्वेर्टी")
    assert not reading.observed
    assert reading.value is None
    assert reading.matched_via is None


def test_a_corpus_attested_spelling_is_the_second_chance(lookup):
    """At CER 0.108 the model's prediction is often a near miss, and the
    corpus's own spelling for that romanization is the honest fallback."""
    reading = lookup.lookup("भारतत", ["भारत"])
    assert reading.value == 6.38
    assert reading.matched_via == "attested_form"


def test_the_commonest_attested_spelling_wins_not_the_first(lookup):
    """An attacker reaches the word by whichever spelling is easiest."""
    reading = lookup.lookup("???", ["प्यार", "भारत"])
    assert reading.value == 6.38


def test_the_attested_fallback_can_be_switched_off():
    """Off, the join is strictly model-mediated -- an arm of the sensitivity
    analysis, because the two routes are not equally trustworthy."""
    strict = FrequencyLookup(source=SOURCE, table={"भारत": 6.38}, use_attested_forms=False)
    assert not strict.lookup("भारतत", ["भारत"]).observed


def test_the_native_form_is_preferred_over_an_attested_one(lookup):
    reading = lookup.lookup("मेरा", ["भारत"])
    assert reading.value == 5.78
    assert reading.matched_via == "native_form"


# -- provenance ------------------------------------------------------------


def test_the_source_identifies_itself_completely():
    """A frequency is uninterpretable without its scale and its table."""
    payload = SOURCE.to_dict()
    assert payload["identifier"] == "fixture-0/hi/small"
    assert "Zipf" in payload["semantics"]
    for key in ("provider", "version", "language", "wordlist", "license", "entries"):
        assert key in payload


def test_an_unknown_provider_is_refused_rather_than_guessed():
    with pytest.raises(FrequencyUnavailable, match="Unknown frequency provider"):
        load_frequency_lookup("hi", provider="vibes")


# -- the real table --------------------------------------------------------


def test_the_shipped_hindi_table_loads_and_ranks_common_words_highly():
    """Against the real wordfreq data, so a version bump that broke the join
    fails here rather than silently producing an unranked dictionary."""
    pytest.importorskip("wordfreq")
    lookup = load_frequency_lookup("hi")

    assert len(lookup) > 10_000
    assert lookup.source.provider == "wordfreq"
    assert "Zipf" in lookup.source.semantics

    bharat = lookup.lookup("भारत")
    rare = lookup.lookup("मस्ते")
    assert bharat.observed
    assert bharat.value > 5.0
    # The suffix `maste` is a corpus artefact, not a Hindi word: the frequency
    # table not knowing it is exactly the signal the ranking needs.
    assert not rare.observed


def test_an_unknown_language_is_refused_with_the_list_of_known_ones():
    pytest.importorskip("wordfreq")
    with pytest.raises(FrequencyUnavailable, match="Available:"):
        load_frequency_lookup("xx-not-a-language")
