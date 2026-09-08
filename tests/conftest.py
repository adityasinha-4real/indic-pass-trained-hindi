"""Shared fixtures for the password-engine tests.

The tests score against a small, hand-written dictionary rather than the real
298k-entry IndicDict. Two reasons: the real one is a build artefact that may
not exist in a fresh checkout, and a test that asserts on wordlist arithmetic
needs sizes it can do in its head.

The fixture's tier *names* are the real ones from ``config/password.yaml``, so
a rename there breaks these tests -- which is the point.

Two dictionaries are offered, because the guess model has two pricing policies
and both must be exercised. :func:`indicdict` has no frequency at all, so every
entry falls back to its provenance tier -- the Milestone 1 behaviour, kept as a
fixture so the fallback cannot rot. :func:`ranked_indicdict` gives the same
words observed frequencies, so they are priced by measured rank instead.
"""

from __future__ import annotations

import pytest

from indicpass.password.dictionary import IndicDict, IndicDictEntry
from indicpass.password.matcher import MatcherSettings
from indicpass.password.meter import IndicPassMeter
from indicpass.password.scoring import ScoringSettings, StrengthScale

TIER_ORDER = ("human_romanized", "curated_entities", "curated_other", "mined")
NAMED_ENTITY_TIERS = ("curated_entities",)

#: Stands in for a real table's identifier in the fixtures. Anything reading a
#: frequency must be able to say where it came from, tests included.
FIXTURE_FREQUENCY_SOURCE = "fixture-frequencies/hi"


def make_entry(
    romanized: str,
    native: str = "नमस्ते",
    *,
    tier: str = "human_romanized",
    source: str = "Dakshina",
    verified: bool = True,
    frequency: float | None = None,
) -> IndicDictEntry:
    return IndicDictEntry(
        romanized_form=romanized,
        native_form=native,
        language="hin",
        tier=tier,
        source=source,
        attested_forms=(native,),
        model_verified=verified,
        variant_count=1,
        frequency=frequency,
        frequency_source=FIXTURE_FREQUENCY_SOURCE if frequency is not None else None,
        frequency_matched_via="native_form" if frequency is not None else None,
    )


#: Deliberately small and with known tier sizes, so a test can state the
#: expected guess count arithmetically instead of pinning a magic number. The
#: third column is a plausible Zipf frequency, used only by the ranked fixture.
FIXTURE_WORDS: tuple[tuple[str, str, float], ...] = (
    ("namaste", "human_romanized", 4.09),
    ("pyaar", "human_romanized", 5.68),
    ("dosti", "human_romanized", 3.90),
    ("bharat", "curated_entities", 6.38),
    ("krishna", "curated_entities", 4.55),
    ("sharma", "curated_entities", 5.10),
    ("jaihind", "curated_other", 2.20),
    ("mera", "curated_other", 5.78),
    ("bahut", "mined", 5.30),
    ("achha", "mined", 4.20),
)

_TIER_SOURCES = {"human_romanized": "Dakshina", "curated_entities": "Wikidata"}


def build_dictionary(*, ranked: bool) -> IndicDict:
    entries = [
        make_entry(
            word,
            tier=tier,
            source=_TIER_SOURCES.get(tier, "IndicCorp"),
            frequency=frequency if ranked else None,
        )
        for word, tier, frequency in FIXTURE_WORDS
    ]
    return IndicDict.from_entries(
        entries,
        language="hin",
        tier_order=TIER_ORDER,
        frequency_source=(
            {"identifier": FIXTURE_FREQUENCY_SOURCE, "semantics": "Zipf"} if ranked else None
        ),
    )


@pytest.fixture
def indicdict() -> IndicDict:
    """Ten words across four tiers, none with an observed frequency."""
    return build_dictionary(ranked=False)


@pytest.fixture
def ranked_indicdict() -> IndicDict:
    """The same ten words, every one priced by a measured rank."""
    return build_dictionary(ranked=True)


@pytest.fixture
def scoring_settings() -> ScoringSettings:
    return ScoringSettings(
        structure_factor=10000.0,
        min_guesses=1.0,
        max_segmentation_depth=12,
        bruteforce_cardinality="observed",
        character_class_sizes={
            "lowercase": 26,
            "uppercase": 26,
            "digits": 10,
            "symbols": 33,
        },
    )


@pytest.fixture
def matcher_settings() -> MatcherSettings:
    return MatcherSettings(
        min_word_length=3,
        min_substring_length=4,
        max_match_length=24,
        allow_substring_matches=True,
        allow_fragment_matches=True,
        class_penalties={
            "exact_word": 1.0,
            "transformed_word": 1.0,
            "substring_word": 1.0,
            "fragment": 10.0,
        },
        digits_per_position=10,
        year_range=(1900, 2035),
        symbol_alphabet_size=33,
        repeat_cardinality=26,
    )


@pytest.fixture
def scale() -> StrengthScale:
    return StrengthScale(
        [1e3, 1e6, 1e8, 1e10],
        ["Very Weak", "Weak", "Fair", "Strong", "Very Strong"],
    )


def build_meter(dictionary, matcher_settings, scoring_settings, scale, **kwargs):
    return IndicPassMeter(
        [dictionary],
        matcher_settings=matcher_settings,
        scoring_settings=scoring_settings,
        scale=scale,
        named_entity_tiers=NAMED_ENTITY_TIERS,
        **kwargs,
    )


@pytest.fixture
def meter(indicdict, matcher_settings, scoring_settings, scale) -> IndicPassMeter:
    return build_meter(indicdict, matcher_settings, scoring_settings, scale)


@pytest.fixture
def ranked_meter(ranked_indicdict, matcher_settings, scoring_settings, scale) -> IndicPassMeter:
    return build_meter(ranked_indicdict, matcher_settings, scoring_settings, scale)


@pytest.fixture
def baseline():
    """The real zxcvbn adapter. Skipped, never stubbed, when it is missing.

    A fake baseline would let the comparison tests pass while saying nothing
    about the estimator the reports were actually produced with.
    """
    from indicpass.password.baseline import BaselineUnavailable, ZxcvbnBaseline

    try:
        return ZxcvbnBaseline()
    except BaselineUnavailable as exc:  # pragma: no cover - environment-dependent
        pytest.skip(str(exc))


@pytest.fixture
def meter_with_baseline(
    indicdict, matcher_settings, scoring_settings, scale, baseline
) -> IndicPassMeter:
    return build_meter(
        indicdict, matcher_settings, scoring_settings, scale, baseline=baseline
    )
