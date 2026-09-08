"""The benchmark corpus: deterministic, controlled, and never written down."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from indicpass.password.benchmark import (
    CATEGORIES,
    ENGLISH_WORDS,
    INDIC_WORDS,
    BenchmarkSample,
    describe_corpus,
    generate_corpus,
)


@pytest.fixture
def corpus() -> list[BenchmarkSample]:
    return generate_corpus(seed=42, samples_per_category=40)


# -- determinism -----------------------------------------------------------


def test_the_same_seed_reproduces_the_corpus_exactly():
    """The corpus is not stored, so the seed IS the artefact."""
    first = generate_corpus(seed=42, samples_per_category=25)
    second = generate_corpus(seed=42, samples_per_category=25)
    assert [(s.sample_id, s.password) for s in first] == [
        (s.sample_id, s.password) for s in second
    ]


def test_a_different_seed_produces_a_different_corpus():
    a = {s.password for s in generate_corpus(seed=1, samples_per_category=25)}
    b = {s.password for s in generate_corpus(seed=2, samples_per_category=25)}
    assert a != b


def test_a_category_is_unaffected_by_which_others_were_generated():
    """Ablations run over subsets, and must compare the same passwords."""
    full = generate_corpus(seed=42, samples_per_category=20)
    alone = generate_corpus(seed=42, samples_per_category=20, categories=["random"])

    expected = [s.password for s in full if s.category == "random"]
    assert [s.password for s in alone] == expected


def test_an_unknown_category_is_refused():
    with pytest.raises(ValueError, match="Unknown benchmark categories"):
        generate_corpus(seed=42, samples_per_category=5, categories=["indic_haiku"])


# -- composition -----------------------------------------------------------


def test_every_category_is_populated(corpus):
    produced = {sample.category for sample in corpus}
    assert produced == set(CATEGORIES)


def test_sample_ids_are_unique_and_name_their_category(corpus):
    ids = [sample.sample_id for sample in corpus]
    assert len(ids) == len(set(ids))
    for sample in corpus:
        assert sample.sample_id.startswith(f"{sample.category}-")


def test_passwords_are_unique_within_a_category(corpus):
    """A repeat would be weighted double in the averages."""
    for category in CATEGORIES:
        passwords = [s.password for s in corpus if s.category == category]
        assert len(passwords) == len(set(passwords)), category


def test_the_indic_categories_are_built_from_indic_words(corpus):
    bank = {word.lower() for word in INDIC_WORDS}
    for sample in corpus:
        if sample.category in {"indic_word", "indic_numeric", "indic_year", "indic_symbol"}:
            assert any(word in sample.password.lower() for word in bank), sample.sample_id


def test_the_year_category_actually_ends_in_a_plausible_year(corpus):
    for sample in corpus:
        if sample.category == "indic_year":
            assert 1950 <= int(sample.password[-4:]) <= 2025


def test_the_random_category_has_no_lexical_structure(corpus):
    """The upper control. If these matched word banks they would not be controls."""
    banks = {w.lower() for w in INDIC_WORDS} | {w.lower() for w in ENGLISH_WORDS}
    for sample in corpus:
        if sample.category == "random":
            assert sample.password.lower() not in banks


def test_the_word_banks_are_not_drawn_from_the_dictionary(indicdict):
    """The instrument must be independent of the thing it measures.

    Sampling IndicDict would guarantee coverage and measure nothing; the point
    of the probe is that some of these words are genuinely missing.
    """
    assert not {w.lower() for w in INDIC_WORDS} <= set(indicdict.entries)


# -- nothing reaches disk --------------------------------------------------


def test_a_sample_label_carries_no_password(corpus):
    for sample in corpus:
        label = sample.label()
        assert "password" not in label
        assert sample.password not in json.dumps(label, ensure_ascii=False)
        assert label["length"] == len(sample.password)


def test_the_corpus_description_carries_no_password(corpus):
    text = json.dumps(describe_corpus(corpus), ensure_ascii=False)
    for sample in corpus:
        assert sample.password not in text


def test_the_description_records_the_generator_version(corpus):
    described = describe_corpus(corpus)
    assert described["generator_version"]
    assert described["total_samples"] == len(corpus)
    assert set(described["categories"]) == set(CATEGORIES)


# -- the committed reports -------------------------------------------------


def _report_files():
    reports = Path(__file__).resolve().parents[1] / "results" / "reports"
    return sorted(reports.glob("*.md")) + sorted(reports.glob("*.json"))


def test_no_composed_password_appears_in_any_committed_report():
    """The property that actually matters, checked against the real files.

    A single-word sample can coincide with a report's text, because the
    single-word categories *are* the committed word banks and the coverage
    tables print those on purpose. A composed password -- word plus digits, a
    symbol, a year, two words, or a random string -- has no such excuse, and
    finding one would mean a report is a cracking wordlist.
    """
    files = _report_files()
    if not files:  # pragma: no cover - a fresh checkout before any run
        pytest.skip("No reports generated yet; run scripts/password_benchmark.py")

    blobs = [path.read_text(encoding="utf-8") for path in files]
    bank = {word.lower() for word in INDIC_WORDS} | {w.lower() for w in ENGLISH_WORDS}

    leaked = [
        (sample.sample_id, sample.category)
        for sample in generate_corpus(seed=42, samples_per_category=200)
        if sample.password.lower() not in bank
        and any(sample.password in text for text in blobs)
    ]
    assert leaked == []


def test_no_committed_report_maps_a_sample_id_to_a_password():
    """Even a published word is harmless only while nothing says which id used it."""
    files = _report_files()
    if not files:  # pragma: no cover
        pytest.skip("No reports generated yet; run scripts/password_benchmark.py")

    for path in files:
        text = path.read_text(encoding="utf-8")
        for sample in generate_corpus(seed=42, samples_per_category=200):
            if sample.sample_id not in text:
                continue
            # The id is present, so the password must not be anywhere near it.
            index = text.index(sample.sample_id)
            window = text[max(0, index - 200) : index + 400]
            assert sample.password not in window, f"{path.name}: {sample.sample_id}"
