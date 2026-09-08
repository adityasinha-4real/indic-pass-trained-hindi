"""IndicDict: rank arithmetic, tier fallback, round-tripping, and the
frequency contract."""

from __future__ import annotations

import json

import pytest

from conftest import FIXTURE_FREQUENCY_SOURCE, TIER_ORDER, make_entry
from indicpass.password.dictionary import (
    OBSERVED_RANK,
    TIER_FALLBACK,
    DictionaryError,
    IndicDict,
    IndicDictEntry,
)

# -- tier structure --------------------------------------------------------


def test_tier_sizes_and_offsets_follow_the_configured_order(indicdict):
    tiers = indicdict.tiers
    assert [tiers[name].index for name in TIER_ORDER] == [0, 1, 2, 3]
    assert tiers["human_romanized"].size == 3
    assert tiers["curated_entities"].size == 3
    assert tiers["curated_other"].size == 2
    assert tiers["mined"].size == 2

    # Offsets accumulate: an attacker exhausts better tiers first.
    assert tiers["human_romanized"].offset == 0
    assert tiers["curated_entities"].offset == 3
    assert tiers["curated_other"].offset == 6
    assert tiers["mined"].offset == 8


def test_expected_position_is_the_midpoint_of_the_tier_after_its_offset(indicdict):
    tier = indicdict.tiers["curated_entities"]
    # 3 entries already tried, then the expected position within 3 unordered.
    assert tier.expected_position == pytest.approx(3 + (3 + 1) / 2)


def test_total_entries_matches_the_index(indicdict):
    assert indicdict.total_entries == len(indicdict) == 10


def test_a_word_in_two_tiers_is_filed_under_the_better_one():
    """Guessing cost is a minimum, so the cheapest place to find a word wins."""
    entries = [
        make_entry("bharat", tier="mined", source="IndicCorp"),
        make_entry("bharat", tier="human_romanized", source="Dakshina"),
    ]
    dictionary = IndicDict.from_entries(entries, language="hin", tier_order=TIER_ORDER)

    assert len(dictionary) == 1
    assert dictionary.get("bharat").tier == "human_romanized"
    assert dictionary.tiers["mined"].size == 0
    assert dictionary.tiers["human_romanized"].size == 1


def test_the_better_tier_wins_regardless_of_insertion_order():
    reversed_order = [
        make_entry("bharat", tier="human_romanized", source="Dakshina"),
        make_entry("bharat", tier="mined", source="IndicCorp"),
    ]
    dictionary = IndicDict.from_entries(reversed_order, language="hin", tier_order=TIER_ORDER)
    assert dictionary.get("bharat").tier == "human_romanized"
    assert dictionary.tiers["mined"].size == 0


def test_an_unknown_tier_is_rejected_rather_than_silently_dropped():
    with pytest.raises(DictionaryError, match="not in the configured tier order"):
        IndicDict.from_entries(
            [make_entry("namaste", tier="invented_tier")],
            language="hin",
            tier_order=TIER_ORDER,
        )


# -- the frequency contract ------------------------------------------------


def test_a_frequency_never_appears_without_the_source_that_produced_it(ranked_indicdict):
    """The invariant the whole guess model rests on.

    A bare number would be uninterpretable and unfalsifiable: "5.1" means
    nothing without "Zipf, from this table, of this native form". So a
    frequency and its provenance stand or fall together, in both directions.
    """
    for entry in ranked_indicdict.entries.values():
        assert (entry.frequency is None) == (entry.frequency_source is None)
        if entry.frequency is not None:
            assert entry.frequency_source == FIXTURE_FREQUENCY_SOURCE
            assert entry.frequency_matched_via in {"native_form", "attested_form"}


def test_an_entry_without_a_frequency_gets_no_rank_and_no_substitute(indicdict):
    """Unknown frequency must stay unknown.

    Silently converting "we do not know" into a tier average would be
    fabrication with extra steps -- the number would look observed and be
    indistinguishable, in the file, from one that was.
    """
    for entry in indicdict.entries.values():
        assert entry.frequency is None
        assert entry.rank is None
        assert entry.frequency_source is None


def test_a_stale_rank_is_cleared_rather_than_trusted():
    """A rank read from a file whose frequency is gone would price a word by a
    wordlist that is not the one being used."""
    entry = make_entry("bharat", frequency=None)
    dictionary = IndicDict.from_entries(
        [IndicDictEntry(**{**entry.to_dict(), "attested_forms": (), "rank": 7})],
        language="hin",
        tier_order=TIER_ORDER,
    )
    assert dictionary.get("bharat").rank is None


def test_model_confidence_is_a_separate_field_from_frequency(indicdict):
    """Section 3 of the milestone brief: a model score is not a word frequency.

    The transliterator is decoded greedily with no calibrated probability, so
    there is nothing to put here -- and the field exists precisely so nothing
    is tempted to put a mining score or a tier position in it instead.
    """
    for entry in indicdict.entries.values():
        assert entry.model_confidence is None
        assert isinstance(entry.model_verified, bool)


def test_variant_count_is_a_real_count_not_a_frequency():
    entry = IndicDictEntry(
        romanized_form="pyaar",
        native_form="प्यार",
        language="hin",
        tier="human_romanized",
        source="Dakshina",
        attested_forms=("प्यार", "पयार"),
        variant_count=2,
    )
    assert entry.variant_count == 2
    assert entry.frequency is None


# -- ranking ---------------------------------------------------------------


def test_ranks_run_from_one_and_order_by_descending_frequency(ranked_indicdict):
    ranked = sorted(
        ranked_indicdict.entries.values(), key=lambda e: e.rank  # type: ignore[arg-type]
    )
    assert [e.rank for e in ranked] == list(range(1, 11))
    # bharat is the commonest word in the fixture, so it is reached first.
    assert ranked[0].romanized_form == "bharat"
    frequencies = [e.frequency for e in ranked]
    assert frequencies == sorted(frequencies, reverse=True)


def test_ranking_ignores_the_tier_a_word_came_from(ranked_indicdict):
    """`mera` is a mined-tier word and one of the commonest in Hindi.

    Provenance says how a pair was produced; frequency says how often the word
    is used. Letting the first override the second would price `mera` at
    100,000 guesses because of where the corpus found it.
    """
    mera = ranked_indicdict.get("mera")
    jaihind = ranked_indicdict.get("jaihind")
    assert mera.tier == "curated_other"
    assert jaihind.tier == "curated_other"
    assert mera.rank < jaihind.rank


def test_a_ranked_word_is_priced_by_its_rank(ranked_indicdict):
    position = ranked_indicdict.guess_position(ranked_indicdict.get("bharat"))
    assert position.policy == OBSERVED_RANK
    assert position.position == 1.0


def test_an_unranked_word_is_priced_by_its_tier_and_says_so(indicdict):
    position = indicdict.guess_position(indicdict.get("krishna"))
    assert position.policy == TIER_FALLBACK
    assert position.tier == "curated_entities"
    assert position.position == pytest.approx(3 + (3 + 1) / 2)


def test_the_fallback_band_starts_after_every_ranked_word():
    """An attacker with frequency data works through what they can order first,
    so an unranked word cannot be cheaper than a ranked one."""
    entries = [
        make_entry("bharat", tier="human_romanized", frequency=6.38),
        make_entry("pyaar", tier="human_romanized", frequency=5.68),
        make_entry("jaihind", tier="human_romanized"),
    ]
    dictionary = IndicDict.from_entries(entries, language="hin", tier_order=TIER_ORDER)

    assert dictionary.ranked_total == 2
    assert dictionary.tiers["human_romanized"].offset == 2
    assert dictionary.guess_position(dictionary.get("jaihind")).position > 2


def test_coverage_reports_the_share_priced_by_evidence(ranked_indicdict, indicdict):
    assert ranked_indicdict.frequency_coverage == 1.0
    assert indicdict.frequency_coverage == 0.0


def test_tier_sizes_split_into_ranked_and_unranked():
    entries = [
        make_entry("bharat", tier="curated_entities", frequency=6.38),
        make_entry("krishna", tier="curated_entities"),
        make_entry("sharma", tier="curated_entities"),
    ]
    tier = IndicDict.from_entries(
        entries, language="hin", tier_order=TIER_ORDER
    ).tiers["curated_entities"]

    assert (tier.size, tier.ranked_size, tier.unranked_size) == (3, 1, 2)
    # Only the two unranked entries are priced by the tier's midpoint.
    assert tier.expected_position == pytest.approx(1 + (2 + 1) / 2)


# -- persistence -----------------------------------------------------------


def test_save_and_load_round_trips(indicdict, tmp_path):
    path = indicdict.save(tmp_path / "indicdict_hin.jsonl")
    reloaded = IndicDict.load(path, language="hin", tier_order=TIER_ORDER)

    assert len(reloaded) == len(indicdict)
    assert reloaded.get("namaste").native_form == indicdict.get("namaste").native_form
    assert {n: t.size for n, t in reloaded.tiers.items()} == {
        n: t.size for n, t in indicdict.tiers.items()
    }


def test_saving_writes_a_provenance_sidecar_declaring_no_frequency(indicdict, tmp_path):
    path = indicdict.save(tmp_path / "indicdict_hin.jsonl", metadata={"git_commit": "abc123"})
    sidecar = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))

    assert sidecar["frequency_available"] is False
    assert sidecar["ranked_entries"] == 0
    assert sidecar["entries"] == 10
    assert sidecar["git_commit"] == "abc123"
    # Tier sizes live in the sidecar because every guess estimate depends on them.
    assert [tier["size"] for tier in sidecar["tiers"]] == [3, 3, 2, 2]


def test_the_sidecar_records_the_frequency_source_when_there_is_one(
    ranked_indicdict, tmp_path
):
    """A guess estimate is only reproducible next to the table it came from."""
    path = ranked_indicdict.save(tmp_path / "indicdict_hin.jsonl")
    sidecar = json.loads(path.with_suffix(".meta.json").read_text(encoding="utf-8"))

    assert sidecar["frequency_available"] is True
    assert sidecar["ranked_entries"] == 10
    assert sidecar["frequency_coverage"] == 1.0
    assert sidecar["frequency_source"]["identifier"] == FIXTURE_FREQUENCY_SOURCE


def test_ranks_are_recomputed_on_load_not_trusted_from_the_file(ranked_indicdict, tmp_path):
    """An ablation loads a subset, and its ranks must refer to the wordlist it
    actually holds -- otherwise every estimate cites a list that was not used."""
    path = ranked_indicdict.save(tmp_path / "indicdict_hin.jsonl")
    lines = path.read_text(encoding="utf-8").splitlines()
    # Drop the commonest word and reload: everything below it moves up one.
    kept = [line for line in lines if '"romanized_form": "bharat"' not in line]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")

    reloaded = IndicDict.load(path, language="hin", tier_order=TIER_ORDER)
    assert reloaded.ranked_total == 9
    assert reloaded.get("mera").rank == 1  # was 2, behind bharat
    assert sorted(e.rank for e in reloaded.entries.values()) == list(range(1, 10))


def test_saved_order_is_deterministic(indicdict, tmp_path):
    first = (tmp_path / "a.jsonl").with_suffix(".jsonl")
    second = (tmp_path / "b.jsonl").with_suffix(".jsonl")
    indicdict.save(first)
    indicdict.save(second)
    assert first.read_text(encoding="utf-8") == second.read_text(encoding="utf-8")


def test_loading_a_missing_dictionary_says_how_to_build_one(tmp_path):
    with pytest.raises(DictionaryError, match="build_indicdict"):
        IndicDict.load(tmp_path / "absent.jsonl", language="hin", tier_order=TIER_ORDER)
