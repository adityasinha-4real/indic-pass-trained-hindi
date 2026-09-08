"""The shipped config/password.yaml must actually build a working meter.

These tests read the real configuration rather than a fixture. Every number in
the guess model lives in that file, so a typo there produces wrong password
scores with no other symptom -- there is no exception to catch and no test
elsewhere that would notice.
"""

from __future__ import annotations

import pytest

from indicpass.config import ConfigError, load_config
from indicpass.password.matcher import MatcherSettings
from indicpass.password.scoring import ScoringSettings, StrengthScale


@pytest.fixture
def config():
    return load_config()


def test_every_section_the_engine_reads_is_present(config):
    for section in (
        "strength",
        "dictionary",
        "frequency",
        "matching",
        "scoring",
        "baseline",
        "evaluation",
    ):
        assert config.password_section(section)


def test_a_missing_section_is_an_error_not_an_empty_default(config):
    """Scoring with half a configuration would produce numbers that look real."""
    with pytest.raises(ConfigError, match="no 'nonexistent' section"):
        config.password_section("nonexistent")


def test_the_thresholds_parse_as_numbers(config):
    """YAML 1.1 reads `1.0e3` as a string; the file must not rely on that working."""
    thresholds = config.password_section("strength")["thresholds"]
    assert all(isinstance(value, (int, float)) for value in thresholds), thresholds


def test_the_shipped_scale_builds_and_spans_0_to_4(config):
    scale = StrengthScale.from_config(config.password_section("strength"))
    assert len(scale.thresholds) == 4
    assert len(scale.labels) == 5
    assert scale.score(0.0) == 0
    assert scale.score(50.0) == 4


def test_the_shipped_settings_build(config):
    matching = config.password_section("matching")
    scoring = config.password_section("scoring")
    MatcherSettings.from_config(matching, scoring)
    ScoringSettings.from_config(scoring, matching)


def test_tier_names_are_unique_and_subsources_are_not_shared(config):
    """A subsource in two tiers would make a word's cost depend on read order."""
    tiers = config.password_section("dictionary")["tiers"]
    names = [tier["name"] for tier in tiers]
    assert len(names) == len(set(names))

    seen: set[str] = set()
    for tier in tiers:
        for subsource in tier["subsources"]:
            assert subsource not in seen, f"{subsource} appears in two tiers"
            seen.add(subsource)


def test_every_aksharantar_hindi_subsource_has_a_tier(config):
    """A subsource with no tier is silently dropped from the dictionary.

    These eight are what data/processed/preprocess_manifest.json records for
    Hindi. If preprocessing ever yields a ninth, this fails rather than quietly
    shrinking the wordlist.
    """
    expected = {
        "IndicCorp",
        "Samanantar",
        "Existing",
        "Dakshina",
        "Wikidata",
        "AK-Freq",
        "AK-NEI",
        "AK-NEF",
    }
    configured = {
        subsource
        for tier in config.password_section("dictionary")["tiers"]
        for subsource in tier["subsources"]
    }
    assert configured == expected


def test_exactly_one_tier_is_marked_as_named_entities(config):
    tiers = config.password_section("dictionary")["tiers"]
    named = [tier["name"] for tier in tiers if tier.get("named_entity")]
    assert named == ["curated_entities"]


def test_the_baseline_is_enabled_and_names_an_implementation(config):
    """Without a baseline no comparative claim is possible, so it ships on."""
    baseline = config.password_section("baseline")
    assert baseline["enabled"] is True
    assert baseline["implementation"] == "zxcvbn"


# -- frequency -------------------------------------------------------------


def test_the_frequency_section_names_a_provider_and_a_language_join(config):
    """A silent hin/hi mis-join yields an empty table and a dictionary that
    merely looks like the frequency-free one, so both halves must be declared."""
    frequency = config.password_section("frequency")
    assert frequency["enabled"] is True
    assert frequency["provider"] == "wordfreq"
    assert frequency["languages"]["hin"] == "hi"


def test_the_match_class_penalties_cover_every_class(config):
    """A missing class would silently score 1.0 -- no correction, no warning."""
    from indicpass.password.matcher import MatchClass

    penalties = config.password_section("matching")["class_penalties"]
    assert set(penalties) == {str(member) for member in MatchClass}
    assert all(float(value) >= 1.0 for value in penalties.values())


def test_a_fragment_is_never_cheaper_evidence_than_a_whole_word(config):
    """The penalty ordering IS the evidence ordering; inverting it would make a
    coincidental 3-letter hit better evidence than the password being the word."""
    penalties = config.password_section("matching")["class_penalties"]
    assert penalties["fragment"] >= penalties["substring_word"]
    assert penalties["substring_word"] >= penalties["exact_word"]


def test_the_substring_threshold_sits_where_hits_stop_being_coincidence(config):
    """Measured on the built dictionary, P(random L-string is a key) is 0.40 at
    L=3 and 0.055 at L=4. Anything below 4 is close to no evidence at all."""
    matching = config.password_section("matching")
    assert matching["min_substring_length"] >= 4
    assert matching["min_word_length"] >= 3


def test_the_bruteforce_cardinality_setting_is_understood(config):
    scoring = config.password_section("scoring")
    raw = scoring["bruteforce_cardinality"]
    assert raw == "observed" or isinstance(raw, int)

    settings = ScoringSettings.from_config(scoring, config.password_section("matching"))
    assert isinstance(settings.cardinality_for("Abc123!"), int)


def test_the_shipped_cardinality_matches_the_baselines(config):
    """Set to a flat 10 after measurement, not intuition.

    The sweep in results/reports/guess_model_sensitivity.md found that the
    alternative -- the observed character classes -- accounted for essentially
    the whole divergence from zxcvbn on random controls, where there is no
    lexical structure for the Indic dictionary to have found. Left there, the
    benchmark would have been measuring an alphabet assumption.
    """
    settings = ScoringSettings.from_config(
        config.password_section("scoring"), config.password_section("matching")
    )
    for password in ("abcdef", "abc123", "Abc123!"):
        assert settings.cardinality_for(password) == 10, password


def test_the_observed_policy_still_works_because_it_is_an_ablation_arm(config):
    """It is reported as an arm of the sensitivity analysis, so it must run."""
    import dataclasses

    settings = dataclasses.replace(
        ScoringSettings.from_config(
            config.password_section("scoring"), config.password_section("matching")
        ),
        bruteforce_cardinality="observed",
    )
    assert settings.cardinality_for("abcdef") == 26
    assert settings.cardinality_for("abc123") == 36
    assert settings.cardinality_for("Abc123!") == 95
