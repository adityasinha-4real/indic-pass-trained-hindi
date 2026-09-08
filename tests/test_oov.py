"""The OOV partition: does it cut the benchmark where it says it does?

The partition decides which population Milestone 3's central claim is tested on,
so the rules are tested one at a time against a dictionary small enough to hold
in your head, and the ordering between them is tested separately -- a rule that
fires when an earlier one should have would move targets between populations
without changing any count.

The two axes are tested apart, because they are different in kind. Dictionary
membership is exact and the headline finding rests on it. The nine partitions
are a heuristic and nothing rests on them, which is why the tests here assert
that the heuristic is *consistent* rather than that it is right about Hindi.
"""

from __future__ import annotations

import json

import pytest

from indicpass.password.benchmark import INDIC_WORDS, generate_corpus
from indicpass.password.oov import (
    INDIC_CATEGORIES,
    MIN_EVIDENCE_LENGTH,
    NAME_WORDS,
    OOV_PARTITIONS,
    PARTITIONS,
    REPORT_GROUPS,
    OovTargetRow,
    TargetClass,
    Taxonomy,
    group_rows,
    partition_counts,
)

#: A dictionary with a known shape: two plain words, one that is a prefix of a
#: longer form, and one spelled the short way so a doubled-vowel variant lands.
WORDS = ("namaste", "bharat", "pyar", "ghar", "dost", "sharma")


@pytest.fixture
def taxonomy() -> Taxonomy:
    return Taxonomy(WORDS)


def classify(taxonomy: Taxonomy, password: str, category: str = "indic_word") -> str:
    return taxonomy.classify(password, category).partition


# -- the word bank ----------------------------------------------------------


def test_every_name_is_still_in_the_benchmark_word_bank():
    """The name list is transcribed from ``benchmark.py``'s comment groups. If a
    word is renamed or dropped there, this is where it is noticed -- otherwise
    ``oov_name`` would quietly stop meaning what the report says it means."""
    missing = sorted(NAME_WORDS - set(INDIC_WORDS))
    assert missing == [], f"NAME_WORDS entries no longer in the benchmark bank: {missing}"


def test_the_name_bank_is_a_proper_subset_of_the_word_bank():
    assert len(NAME_WORDS) < len(INDIC_WORDS)
    assert "namaste" not in NAME_WORDS  # a greeting, not a name
    assert "sharma" in NAME_WORDS  # a surname
    assert "bharat" in NAME_WORDS  # a place


# -- the body ---------------------------------------------------------------


def test_the_body_is_the_leading_letter_run_lower_cased(taxonomy):
    assert taxonomy.body_of("Namaste2019") == "namaste"
    assert taxonomy.body_of("GHAR@42") == "ghar"
    assert taxonomy.body_of("dost") == "dost"
    assert taxonomy.body_of("123abc") == ""
    assert taxonomy.body_of("") == ""


def test_the_body_stops_at_the_first_non_ascii_letter(taxonomy):
    assert taxonomy.body_of("ghar-mera") == "ghar"
    assert taxonomy.body_of("नमस्ते") == ""


# -- the rules, one at a time -----------------------------------------------


def test_a_dictionary_word_is_in_lexicon(taxonomy):
    assert classify(taxonomy, "namaste") == "indic_in_lexicon"
    assert classify(taxonomy, "Namaste2019") == "indic_in_lexicon"
    assert taxonomy.classify("namaste", "indic_word").in_lexicon is True


def test_a_missing_name_is_a_name_before_anything_else(taxonomy):
    """``krishna`` is in the benchmark's name bank and not in this dictionary."""
    assert classify(taxonomy, "krishna") == "oov_name"
    assert taxonomy.classify("krishna", "indic_word").is_name is True


def test_a_respelling_of_a_known_word_is_a_transliteration_variant(taxonomy):
    """``pyaar`` is missing; ``pyar`` is present; the doubled-vowel rule joins
    them. This is the largest single reason a real spelling misses a dictionary
    built from one corpus."""
    assert classify(taxonomy, "pyaar") == "oov_spelling_variant"
    assert taxonomy.classify("pyaar", "indic_word").variant_in_lexicon is True


def test_a_known_root_with_a_short_ending_is_morphological(taxonomy):
    """``gharon`` is ``ghar`` plus a two-character oblique plural ending."""
    assert classify(taxonomy, "gharon") == "oov_morphological_variant"
    detail = taxonomy.classify("gharon", "indic_word")
    assert detail.known_prefix_length == len("ghar")


def test_a_known_word_with_a_long_tail_is_a_stem_and_suffix(taxonomy):
    """Four characters left over is past the inflection band, so the same root
    lands in the next family instead. The boundary is where it is documented."""
    assert classify(taxonomy, "gharwale") == "oov_stem_suffix"
    assert classify(taxonomy, "gharwalonko") == "oov_stem_suffix"


def test_a_known_word_buried_inside_is_a_stem_and_suffix(taxonomy):
    assert classify(taxonomy, "medostiya") == "oov_stem_suffix"


def test_something_with_no_evidence_at_all_is_other(taxonomy):
    assert classify(taxonomy, "zzqqxxww") == "oov_other"


def test_the_controls_are_taken_before_any_lexical_rule(taxonomy):
    """A random string that happens to start with a dictionary word must stay a
    control. Folding it into a lexical population would put noise in the
    numbers the milestone turns on."""
    assert classify(taxonomy, "namastexyz", "random") == "random_control"
    assert classify(taxonomy, "namaste", "english") == "english_control"
    assert classify(taxonomy, "namastebharat", "mixed") == "mixed_construction"


def test_a_control_still_records_its_dictionary_membership(taxonomy):
    """The partition says which population it is; ``in_lexicon`` says what the
    dictionary knows. An English word with a Devanagari transliteration is both
    a control and a dictionary entry, and the report has to be able to say so."""
    detail = taxonomy.classify("namaste", "english")
    assert detail.partition == "english_control"
    assert detail.in_lexicon is True


def test_a_password_with_no_letters_falls_through_to_other(taxonomy):
    detail = taxonomy.classify("12345678", "indic_numeric")
    assert detail.partition == "oov_other"
    assert detail.body_length == 0
    assert detail.in_lexicon is False


# -- rule ordering ----------------------------------------------------------


def test_membership_beats_every_out_of_lexicon_rule(taxonomy):
    """``sharma`` is both a dictionary key and a name. It is in-lexicon, and the
    OOV families are for what the dictionary does not have."""
    assert "sharma" in NAME_WORDS
    assert classify(taxonomy, "sharma") == "indic_in_lexicon"


def test_a_name_that_is_also_a_variant_is_reported_as_a_name(taxonomy):
    """Rules are ordered, and the order is the documented one: the name bank is
    consulted before the respelling rules, so a missing name never lands in the
    transliteration family."""
    extended = Taxonomy((*WORDS, "krishn"))
    assert extended.classify("krishna", "indic_word").variant_in_lexicon is True
    assert classify(extended, "krishna") == "oov_name"


def test_every_target_gets_exactly_one_partition(taxonomy):
    corpus = generate_corpus(seed=42, samples_per_category=25)
    assigned = [taxonomy.classify(s.password, s.category).partition for s in corpus]
    assert len(assigned) == len(corpus)
    assert set(assigned) <= set(PARTITIONS)


# -- variants ---------------------------------------------------------------


def test_the_variant_set_is_bounded_and_excludes_the_word_itself(taxonomy):
    variants = taxonomy.variants("dhanyavaad")
    assert "dhanyavaad" not in variants
    assert len(variants) == len(set(variants))
    assert len(variants) <= 25


def test_the_variant_rules_collapse_and_expand_long_vowels(taxonomy):
    assert "pyar" in taxonomy.variants("pyaar")
    assert "paani" in taxonomy.variants("pani")


# -- groups -----------------------------------------------------------------


def make_row(sample_id: str, category: str, detail: TargetClass, **changes) -> OovTargetRow:
    defaults = {
        "reachable": True,
        "rank": 10,
        "log10_rank": 1.0,
        "shape": "stem/lower",
        "level": 20,
        "reason": None,
        "predictions": {"indicpass": 3.0, "pcfg": 2.0, "baseline": 4.0},
    }
    return OovTargetRow(
        sample_id=sample_id,
        category=category,
        construction=f"{category}/lower",
        length=7,
        classification=detail,
        **{**defaults, **changes},
    )


@pytest.fixture
def rows(taxonomy) -> list[OovTargetRow]:
    corpus = generate_corpus(seed=42, samples_per_category=20)
    return [
        make_row(
            sample.sample_id,
            sample.category,
            taxonomy.classify(sample.password, sample.category),
            reachable=index % 3 != 0,
            rank=None if index % 3 == 0 else index + 1,
            log10_rank=None if index % 3 == 0 else float(index + 1) ** 0.5,
            reason="stem_too_long" if index % 3 == 0 else None,
        )
        for index, sample in enumerate(corpus)
    ]


def test_the_membership_groups_are_a_clean_split(rows):
    inside = group_rows(rows, "in_lexicon")
    outside = group_rows(rows, "oov")
    assert len(inside) + len(outside) == len(rows)
    assert not {row.sample_id for row in inside} & {row.sample_id for row in outside}


def test_the_indic_oov_group_is_indic_and_out_of_lexicon(rows):
    for row in group_rows(rows, "oov_indic"):
        assert row.in_lexicon is False
        assert row.category in INDIC_CATEGORIES


def test_the_partition_named_like_a_group_is_a_subset_of_it(rows):
    """``indic_in_lexicon`` and ``in_lexicon`` are different populations that
    would be easy to confuse. The names are spelled apart, and the containment
    is asserted so a table can never quietly show one for the other."""
    partition = {row.sample_id for row in group_rows(rows, "indic_in_lexicon")}
    group = {row.sample_id for row in group_rows(rows, "in_lexicon")}
    assert partition <= group


def test_every_documented_group_resolves(rows):
    for group in REPORT_GROUPS:
        assert isinstance(group_rows(rows, group), list)


def test_an_unknown_group_is_refused(rows):
    with pytest.raises(ValueError, match="Unknown reporting group"):
        group_rows(rows, "by_vibes")


def test_the_partitions_cover_every_row_exactly_once(rows):
    counted = sum(len(group_rows(rows, name)) for name in PARTITIONS)
    assert counted == len(rows)


def test_partition_counts_report_coverage_without_dividing_by_zero(rows):
    summary = partition_counts(rows)
    assert set(summary) == set(PARTITIONS)
    for entry in summary.values():
        assert 0.0 <= entry["coverage"] <= 1.0
        assert entry["reachable"] <= entry["targets"]
    assert set(summary) >= set(OOV_PARTITIONS)


# -- rows -------------------------------------------------------------------


def test_a_row_carries_no_password(rows):
    payload = json.dumps([row.to_dict() for row in rows])
    corpus = generate_corpus(seed=42, samples_per_category=20)
    for sample in corpus:
        if len(sample.password) >= 8:
            assert sample.password not in payload


def test_an_unreachable_row_carries_a_reason_and_no_rank(rows):
    for row in rows:
        if row.reachable:
            assert row.rank is not None and row.reason is None
        else:
            assert row.rank is None and row.reason is not None


def test_a_row_converts_to_the_milestone_4_statistics_shape(rows):
    """The metric code is frozen and shared. A second implementation of Spearman
    would be a second thing to be wrong."""
    for row in rows[:20]:
        plain = row.as_validation_row()
        assert plain.sample_id == row.sample_id
        assert plain.covered is row.reachable
        assert plain.reference_rank == row.rank
        assert plain.unseen_stem is (not row.in_lexicon)
        assert plain.predictions == dict(row.predictions)


def test_the_row_dict_names_the_partition_and_the_membership(rows):
    payload = rows[0].to_dict()
    assert payload["partition"] in PARTITIONS
    assert isinstance(payload["in_lexicon"], bool)
    assert "attack_rank" in payload
    assert "exclusion_reason" in payload


# -- the real dictionary ----------------------------------------------------


def test_the_real_dictionary_leaves_a_measurable_oov_population():
    """The milestone only has a subject if the benchmark actually contains
    out-of-lexicon Indic words. Milestone 4 measured 872 unreachable targets;
    this asserts the population is still there and is not a rounding error."""
    from indicpass.config import load_config
    from indicpass.password.character_attack import dictionary_stem_corpus
    from indicpass.password.dictionary import IndicDict

    config = load_config()
    dictionary_config = config.password_section("dictionary")
    path = config.resolve(dictionary_config["files"]["hin"])
    if not path.is_file():  # pragma: no cover - dictionary not built here
        pytest.skip("IndicDict not built in this checkout.")

    tier_order = [str(tier["name"]) for tier in dictionary_config["tiers"]]
    dictionary = IndicDict.load(path, language="hin", tier_order=tier_order)
    taxonomy = Taxonomy(dictionary_stem_corpus(dictionary))

    corpus = generate_corpus(seed=42, samples_per_category=200)
    indic = [s for s in corpus if s.category in INDIC_CATEGORIES]
    classes = [taxonomy.classify(s.password, s.category) for s in indic]
    oov = [entry for entry in classes if not entry.in_lexicon]
    assert len(oov) > 100, "no out-of-lexicon population left to test the claim on"
    assert len({entry.partition for entry in oov}) > 1, (
        "every out-of-lexicon target landed in one family; the partition is not "
        "separating anything"
    )


def test_the_minimum_evidence_length_matches_the_matcher():
    """Four characters is the floor everywhere in this project, and it is a
    measured one: a three-letter hit occurs in 40% of random strings."""
    from indicpass.config import load_config

    matching = load_config().password_section("matching")
    assert int(matching["min_substring_length"]) == MIN_EVIDENCE_LENGTH


def test_no_row_level_label_contains_a_benchmark_password():
    """A label printed beside a ``sample_id`` must not spell one of the corpus's
    passwords, even by accident inside a longer English word.

    ``test_benchmark.py`` checks that no report puts a password within 400
    characters of the id that used it, and it cannot tell a leak from a
    coincidence -- correctly, because a reader could not either. The partition
    ``oov_transliteration_variant`` failed it on the substring ``tera`` in
    "transli*tera*tion", which is why the family is called
    ``oov_spelling_variant``. This is the check that keeps a future rename from
    quietly reintroducing the problem.
    """
    from indicpass.password.character_attack import (
        UNREACHABLE_REASONS,
        CharacterAttackSettings,
        build_shapes,
    )

    passwords = {sample.password for sample in generate_corpus(seed=42, samples_per_category=200)}
    labels = [
        *PARTITIONS,
        *REPORT_GROUPS,
        *UNREACHABLE_REASONS,
        *(shape.name for shape in build_shapes(CharacterAttackSettings())),
    ]
    collisions = {
        label: sorted(word for word in passwords if word in label)
        for label in labels
        if any(word in label for word in passwords)
    }
    assert collisions == {}, (
        f"These labels spell a benchmark password: {collisions}. A report row would "
        "then look as though it named the password its sample_id used."
    )
