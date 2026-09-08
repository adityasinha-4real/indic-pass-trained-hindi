"""The reference attack: is the enumeration what it claims to be?

Three things are worth testing here and they are quite different in kind.

The **rank arithmetic** is exact, so it is tested against ground truth: a tiny
attack is enumerated in full, candidate by candidate, and every rank the module
computes is checked against the position that candidate actually occupies in
the list. Nothing is pinned to a magic number.

The **ordering** is the attack's definition, so it is tested for the properties
the design doc claims: deterministic, independent of the dictionary's iteration
order, and different when the seed differs.

The **independence** from the estimators is the claim the whole milestone rests
on, so it is tested twice -- once by parsing this module's imports, and once by
ranking a corpus with the three estimators replaced by objects that raise on
contact.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from itertools import product
from pathlib import Path

import pytest

from conftest import FIXTURE_WORDS, build_dictionary
from indicpass.password.benchmark import generate_corpus
from indicpass.password.dictionary import IndicDict
from indicpass.password.reference_attack import (
    ATTACK_SYMBOLS,
    ATTACK_VERSION,
    LEXICON_ORDERS,
    RULE_ORDERS,
    AttackSettings,
    Lexicon,
    ReferenceAttack,
    Rule,
    Suffix,
    _stem_word,
    build_rules,
    coverage,
    dictionary_lexicon_entries,
)

# -- fixtures ---------------------------------------------------------------

#: Four words with no concatenation ambiguity, so the enumeration test's
#: expectations are unambiguous even where two blocks could collide.
TINY_WORDS: tuple[tuple[str, int | None], ...] = (
    ("alpha", 2),
    ("beta", 1),
    ("gamma", None),
    ("delta", 3),
)


def tiny_settings(**changes) -> AttackSettings:
    """A settings object small enough that the whole universe is enumerable."""
    base = AttackSettings(
        lexicon_order="frequency",
        seed=7,
        max_candidates=1e9,
        year_range=(2000, 2002),
        symbols="!@",
        max_digits=1,
        max_symbol_digits=1,
        combinator=True,
        rule_order="size",
    )
    return base if not changes else type(base)(**{**vars(base), **changes})


@pytest.fixture
def tiny_lexicon() -> Lexicon:
    return Lexicon.build(TINY_WORDS, order="frequency", seed=7)


@pytest.fixture
def tiny_attack(tiny_lexicon: Lexicon) -> ReferenceAttack:
    return ReferenceAttack.build(tiny_lexicon, tiny_settings())


# -- the lexicon ------------------------------------------------------------


def test_frequency_ordering_places_ranked_entries_first_in_rank_order():
    lexicon = Lexicon.build(TINY_WORDS, order="frequency", seed=7)
    assert lexicon.words[:3] == ("beta", "alpha", "delta")
    # The one entry with no observed frequency cannot be ordered by evidence,
    # so it lands in the shuffled tail rather than being given a position.
    assert lexicon.words[3] == "gamma"
    assert lexicon.frequency_ordered == 3


def test_shuffled_ordering_uses_no_frequency_at_all():
    lexicon = Lexicon.build(TINY_WORDS, order="shuffled", seed=7)
    assert lexicon.frequency_ordered == 0
    assert sorted(lexicon.words) == sorted(word for word, _ in TINY_WORDS)


def test_length_ordering_is_shortest_then_alphabetical():
    lexicon = Lexicon.build(TINY_WORDS, order="length", seed=7)
    assert lexicon.words == ("beta", "alpha", "delta", "gamma")
    assert lexicon.frequency_ordered == 0


def test_the_lexicon_does_not_depend_on_the_input_order():
    """A dictionary loaded from a differently-ordered file must give the same
    attack, or no rank is reproducible."""
    forwards = Lexicon.build(TINY_WORDS, order="frequency", seed=7)
    backwards = Lexicon.build(reversed(TINY_WORDS), order="frequency", seed=7)
    assert forwards.words == backwards.words
    assert forwards.fingerprint() == backwards.fingerprint()


@pytest.mark.parametrize("order", LEXICON_ORDERS)
def test_every_ordering_is_deterministic(order: str):
    first = Lexicon.build(TINY_WORDS, order=order, seed=7)
    second = Lexicon.build(TINY_WORDS, order=order, seed=7)
    assert first.words == second.words
    assert first.fingerprint() == second.fingerprint()


def test_a_different_seed_reorders_the_unranked_tail():
    words = tuple((f"word{index:03d}", None) for index in range(200))
    first = Lexicon.build(words, order="shuffled", seed=1)
    second = Lexicon.build(words, order="shuffled", seed=2)
    assert first.words != second.words
    assert first.fingerprint() != second.fingerprint()
    assert sorted(first.words) == sorted(second.words)


def test_the_fingerprint_separates_the_orderings():
    prints = {
        order: Lexicon.build(TINY_WORDS, order=order, seed=7).fingerprint()
        for order in LEXICON_ORDERS
    }
    assert len(set(prints.values())) == len(LEXICON_ORDERS)


def test_an_unknown_ordering_is_refused():
    with pytest.raises(ValueError, match="Unknown lexicon order"):
        Lexicon.build(TINY_WORDS, order="by_vibes")


def test_the_lexicon_can_be_capped():
    lexicon = Lexicon.build(TINY_WORDS, order="frequency", seed=7, size=2)
    assert len(lexicon) == 2
    assert lexicon.position("gamma") is None


def test_the_lexicon_description_publishes_no_spelling():
    described = json.dumps(Lexicon.build(TINY_WORDS, order="frequency", seed=7).describe())
    for word, _ in TINY_WORDS:
        assert word not in described


# -- suffix families --------------------------------------------------------


def test_suffix_sizes_are_the_stated_arithmetic():
    assert Suffix("", "none").size == 1
    assert Suffix("digits3", "digits", digits=3).size == 1000
    assert Suffix("year", "year", year_range=(1940, 2029)).size == 90
    assert Suffix("symbol", "symbol", symbols=ATTACK_SYMBOLS).size == len(ATTACK_SYMBOLS)
    assert (
        Suffix("symbol+digits2", "symbol_digits", digits=2, symbols="!@").size == 2 * 100
    )


def test_digit_suffixes_keep_leading_zeros():
    """``007`` is the seventh member of the three-digit family, not of the
    one-digit family: an attacker enumerating 000..999 really does emit it
    there."""
    three = Suffix("digits3", "digits", digits=3)
    assert three.split("bharat007") == ("bharat", 7)
    assert three.split("bharat786") == ("bharat", 786)
    one = Suffix("digits1", "digits", digits=1)
    assert one.split("bharat007") == ("bharat00", 7)


def test_the_year_family_only_matches_inside_its_window():
    years = Suffix("year", "year", year_range=(1940, 2029))
    assert years.split("mera1999") == ("mera", 59)
    assert years.split("mera2029") == ("mera", 89)
    assert years.split("mera1899") is None
    assert years.split("mera2030") is None


def test_symbol_and_symbol_digit_families_invert_correctly():
    symbol = Suffix("symbol", "symbol", symbols="!@#")
    assert symbol.split("mera@") == ("mera", 1)
    assert symbol.split("mera%") is None

    combined = Suffix("symbol+digits2", "symbol_digits", digits=2, symbols="!@#")
    assert combined.split("mera@07") == ("mera", 1 * 100 + 7)
    assert combined.split("mera%07") is None
    assert combined.split("meraa07") is None


def test_a_suffix_never_consumes_the_whole_target():
    """A rule with no stem left has no lexicon entry to have come from."""
    assert Suffix("digits3", "digits", digits=3).split("123") is None
    assert Suffix("symbol", "symbol", symbols="!").split("!") is None


def test_non_ascii_digits_are_not_digits():
    """``str.isdigit`` is true for Devanagari numerals, which an ASCII rule set
    does not enumerate."""
    assert Suffix("digits3", "digits", digits=3).split("mera१२३") is None


# -- case handling ----------------------------------------------------------


def test_the_case_forms_invert_to_the_lexicon_entry():
    assert _stem_word("namaste", "lower") == "namaste"
    assert _stem_word("Namaste", "capitalized") == "namaste"
    assert _stem_word("NAMASTE", "upper") == "namaste"
    assert _stem_word("Namaste", "lower") is None
    assert _stem_word("namaste", "capitalized") is None
    assert _stem_word("NaMaSte", "capitalized") is None


def test_a_caseless_stem_belongs_to_the_lower_rule_alone():
    """Without the guard, ``123`` would be emitted by all three case rules and
    reached three times over."""
    assert _stem_word("123", "lower") == "123"
    assert _stem_word("123", "capitalized") is None
    assert _stem_word("123", "upper") is None


# -- the rule programme -----------------------------------------------------


def test_a_rule_is_the_product_of_its_base_and_its_suffix():
    rule = Rule("word2", "lower", Suffix("digits2", "digits", digits=2))
    assert rule.base_size(100) == 10_000
    assert rule.size(100) == 1_000_000
    assert rule.name == "word+word+digits2/lower"


def test_size_ordering_places_the_cheapest_rules_first():
    rules = build_rules(tiny_settings(rule_order="size"), 4)
    sizes = [rule.size(4) for rule in rules]
    assert sizes == sorted(sizes)


def test_family_ordering_runs_single_words_before_combinations():
    rules = build_rules(tiny_settings(rule_order="family"), 4)
    bases = [rule.base for rule in rules]
    assert bases.index("word2") > max(
        index for index, base in enumerate(bases) if base == "word"
    )


def test_turning_off_the_combinator_removes_every_two_word_rule():
    rules = build_rules(tiny_settings(combinator=False), 4)
    assert all(rule.base == "word" for rule in rules)


def test_an_unknown_rule_order_is_refused():
    with pytest.raises(ValueError, match="Unknown rule order"):
        build_rules(tiny_settings(rule_order="by_vibes"), 4)


# -- rank arithmetic, against ground truth ----------------------------------


def enumerate_attack(attack: ReferenceAttack) -> list[str]:
    """Every candidate the attack emits, in order. Test-side and independent.

    Re-derives the enumeration semantics from the rule definitions rather than
    from :meth:`ReferenceAttack.rank`, so agreeing with it means something.
    """
    words = attack.lexicon.words
    size = len(words)
    emitted: list[str] = []

    def cased(word: str, case: str) -> str:
        return {"lower": word, "capitalized": word.capitalize(), "upper": word.upper()}[case]

    def suffixes(suffix: Suffix) -> list[str]:
        if suffix.kind == "none":
            return [""]
        if suffix.kind == "digits":
            return [str(value).zfill(suffix.digits) for value in range(10**suffix.digits)]
        if suffix.kind == "year":
            low, high = suffix.year_range
            return [str(value) for value in range(low, high + 1)]
        if suffix.kind == "symbol":
            return list(suffix.symbols)
        return [
            symbol + str(value).zfill(suffix.digits)
            for symbol in suffix.symbols
            for value in range(10**suffix.digits)
        ]

    for block in attack.blocks:
        rule = block.rule
        if rule.base == "word":
            stems = [cased(word, rule.case) for word in words]
        else:
            stems = [
                cased(first, rule.case) + second for first in words for second in words
            ]
        assert len(stems) == rule.base_size(size)
        tails = suffixes(rule.suffix)
        assert len(tails) == rule.suffix.size
        emitted.extend(stem + tail for stem in stems for tail in tails)

    assert len(emitted) == attack.universe_size
    return emitted


def test_every_rank_matches_the_position_in_a_full_enumeration(tiny_attack):
    """The strongest form of the claim: the arithmetic is checked against the
    list it is a closed form for, candidate by candidate."""
    emitted = enumerate_attack(tiny_attack)
    first_seen: dict[str, int] = {}
    for position, candidate in enumerate(emitted, start=1):
        first_seen.setdefault(candidate, position)

    assert len(first_seen) > 1000
    for candidate, expected in first_seen.items():
        observed = tiny_attack.rank(candidate)
        assert observed.covered, candidate
        assert observed.rank == expected, candidate
        assert observed.log10_rank == pytest.approx(math.log10(expected))


def test_an_ambiguous_candidate_is_reached_at_its_earliest_reading():
    """A string two rules can produce is emitted by whichever comes first, and
    the rank must be that one -- not the later, larger position.

    ``alpha`` is in the lexicon and is also ``al`` + ``pha``, so it is emitted
    by ``word/lower`` and again, far later, by ``word+word/lower``.
    """
    lexicon = Lexicon.build(
        (("al", 1), ("pha", 2), ("alpha", 3), ("beta", 4)), order="frequency", seed=7
    )
    attack = ReferenceAttack.build(lexicon, tiny_settings())
    emitted = enumerate_attack(attack)
    duplicated = {candidate for candidate in emitted if emitted.count(candidate) > 1}
    assert "alpha" in duplicated

    for candidate in sorted(duplicated)[:20]:
        assert attack.rank(candidate).rank == emitted.index(candidate) + 1
    assert attack.rank("alpha").rule == "word/lower"


def test_blocks_tile_the_universe_without_gaps(tiny_attack):
    offset = 0
    for block in tiny_attack.blocks:
        assert block.offset == offset
        offset += block.size
    assert offset == tiny_attack.universe_size


def test_a_word_outside_the_lexicon_is_uncovered_and_given_no_rank(tiny_attack):
    observed = tiny_attack.rank("epsilon")
    assert observed.covered is False
    assert observed.rank is None
    assert observed.log10_rank is None
    assert observed.rule is None


def test_an_uncovered_target_is_never_given_the_universe_size(tiny_attack):
    """The one substitution that would look plausible and destroy the metric."""
    observed = tiny_attack.rank("epsilon9999999")
    assert observed.rank is None
    assert observed.rank != tiny_attack.universe_size


def test_the_empty_password_is_uncovered(tiny_attack):
    assert tiny_attack.rank("").covered is False


def test_the_rank_names_the_rule_that_produced_it(tiny_attack):
    assert tiny_attack.rank("alpha").rule == "word/lower"
    assert tiny_attack.rank("Alpha").rule == "word/capitalized"
    assert tiny_attack.rank("ALPHA").rule == "word/upper"
    assert tiny_attack.rank("alpha2001").rule == "word+year/lower"
    assert tiny_attack.rank("alpha!").rule == "word+symbol/lower"
    assert tiny_attack.rank("alphabeta").rule == "word+word/lower"


def test_a_year_is_reached_by_the_year_rule_not_the_four_digit_rule():
    """Years are a smaller block, so they sort earlier and the minimum picks
    them -- which is the whole reason a separate year family exists."""
    lexicon = Lexicon.build(TINY_WORDS, order="frequency", seed=7)
    attack = ReferenceAttack.build(lexicon, tiny_settings(max_digits=4, max_candidates=1e12))
    assert attack.rank("alpha2001").rule == "word+year/lower"
    # Outside the window there is no year rule to use, so the generic run pays.
    assert attack.rank("alpha3001").rule == "word+digits4/lower"


# -- the budget -------------------------------------------------------------


def test_the_budget_drops_the_most_expensive_rules_and_names_them(tiny_lexicon):
    generous = ReferenceAttack.build(tiny_lexicon, tiny_settings())
    frugal = ReferenceAttack.build(tiny_lexicon, tiny_settings(max_candidates=100))
    assert len(frugal.blocks) < len(generous.blocks)
    assert frugal.universe_size < generous.universe_size
    assert frugal.dropped
    assert set(frugal.dropped) <= {block.name for block in generous.blocks}


def test_a_password_only_a_dropped_rule_could_reach_is_uncovered(tiny_lexicon):
    frugal = ReferenceAttack.build(tiny_lexicon, tiny_settings(max_candidates=40))
    assert frugal.rank("alpha").covered is True
    assert frugal.rank("alphabeta").covered is False


def test_an_unaffordable_budget_is_an_error_not_an_empty_attack(tiny_lexicon):
    with pytest.raises(ValueError, match="No rule fits"):
        ReferenceAttack.build(tiny_lexicon, tiny_settings(max_candidates=1))


def test_an_empty_lexicon_is_an_error():
    with pytest.raises(ValueError, match="lexicon is empty"):
        ReferenceAttack.build(Lexicon.build((), order="frequency"), tiny_settings())


# -- stems ------------------------------------------------------------------


def test_stem_membership_uses_the_same_machinery_as_the_rank(tiny_attack):
    assert tiny_attack.stem_in_lexicon("alpha1234") is True
    assert tiny_attack.stem_in_lexicon("Alpha!99") is True
    assert tiny_attack.stem_in_lexicon("ALPHA") is True
    assert tiny_attack.stem_in_lexicon("alphabeta7") is True
    assert tiny_attack.stem_in_lexicon("epsilon99") is False
    assert tiny_attack.stem_in_lexicon("1234") is False


# -- determinism ------------------------------------------------------------


def test_two_builds_agree_on_the_fingerprint_and_on_every_rank(tiny_lexicon):
    first = ReferenceAttack.build(tiny_lexicon, tiny_settings())
    second = ReferenceAttack.build(
        Lexicon.build(TINY_WORDS, order="frequency", seed=7), tiny_settings()
    )
    assert first.fingerprint() == second.fingerprint()
    candidates = enumerate_attack(first)[:500]
    assert [first.rank(c).rank for c in candidates] == [
        second.rank(c).rank for c in candidates
    ]


def test_the_fingerprint_moves_when_the_attack_does(tiny_lexicon):
    base = ReferenceAttack.build(tiny_lexicon, tiny_settings()).fingerprint()
    for change in (
        {"rule_order": "family"},
        {"max_candidates": 500.0},
        {"combinator": False},
        {"year_range": (2000, 2010)},
        {"symbols": "!"},
    ):
        assert (
            ReferenceAttack.build(tiny_lexicon, tiny_settings(**change)).fingerprint() != base
        )


def test_ranking_holds_no_state_between_calls(tiny_attack):
    once = tiny_attack.rank("alpha2001")
    for _ in range(5):
        tiny_attack.rank("beta!7")
    assert tiny_attack.rank("alpha2001") == once


# -- independence from the estimators ---------------------------------------

#: Modules whose appearance in the attack's imports would make the validation
#: circular. This list is the leakage safeguard, in the only form a test can
#: check mechanically.
FORBIDDEN_IMPORTS = (
    "indicpass.password.meter",
    "indicpass.password.scoring",
    "indicpass.password.matcher",
    "indicpass.password.baseline",
    "indicpass.password.pcfg",
    "indicpass.password.experiment",
    "indicpass.password.validation",
    "zxcvbn",
)


def attack_module_imports() -> set[str]:
    """Every module `reference_attack.py` imports, from its AST.

    Parsed, not grepped: a comment mentioning zxcvbn must not fail the checks
    below, and an import hidden inside a function must not pass them.
    """
    source = Path(
        __import__("indicpass.password.reference_attack", fromlist=["x"]).__file__
    ).read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    return imported


def test_the_attack_module_imports_no_estimator():
    for name in attack_module_imports():
        assert not name.startswith(FORBIDDEN_IMPORTS), (
            f"reference_attack.py imports {name!r}. Deriving the reference ordering "
            "from an estimator would make the validation circular."
        )


def test_the_attack_module_imports_nothing_but_the_standard_library():
    """The strongest form of the independence claim, and the cheapest to check.

    A denylist can only refuse the estimators someone thought of. This refuses
    every project module at once, including ones that do not exist yet.
    """
    outside = {
        name
        for name in attack_module_imports()
        if name != "__future__" and name.split(".")[0] not in sys.stdlib_module_names
    }
    assert outside == set(), (
        f"reference_attack.py imports {sorted(outside)}. The attack must depend on "
        "nothing that could carry an estimator's output into the candidate ordering."
    )


class Exploding:
    """Raises on any contact. Stands in for the three estimators."""

    def __getattr__(self, name: str):  # pragma: no cover - the point is to raise
        raise AssertionError(
            f"The reference attack touched an estimator ({name}). Candidate "
            "generation must not depend on any estimator's output."
        )

    def __call__(self, *args, **kwargs):  # pragma: no cover - the point is to raise
        raise AssertionError("The reference attack called an estimator.")


def test_ranking_a_corpus_never_touches_an_estimator(monkeypatch):
    """The dynamic half of the leakage check: same ranks with the estimators
    replaced by objects that raise."""
    import indicpass.password.baseline as baseline_module
    import indicpass.password.meter as meter_module
    import indicpass.password.pcfg.estimator as pcfg_module

    lexicon = Lexicon.build(TINY_WORDS, order="frequency", seed=7)
    attack = ReferenceAttack.build(lexicon, tiny_settings())
    samples = generate_corpus(seed=42, samples_per_category=5)
    before = [attack.rank(sample.password).rank for sample in samples]

    monkeypatch.setattr(meter_module, "IndicPassMeter", Exploding())
    monkeypatch.setattr(pcfg_module, "PcfgEstimator", Exploding())
    monkeypatch.setattr(baseline_module, "load_baseline", Exploding())

    rebuilt = ReferenceAttack.build(
        Lexicon.build(TINY_WORDS, order="frequency", seed=7), tiny_settings()
    )
    after = [rebuilt.rank(sample.password).rank for sample in samples]
    assert after == before


# -- controls ---------------------------------------------------------------


def test_the_attack_reaches_almost_no_random_string():
    """The control that decides whether any Indic rank is believable."""
    dictionary = build_dictionary(ranked=True)
    lexicon = Lexicon.build(dictionary_lexicon_entries(dictionary), order="frequency")
    attack = ReferenceAttack.build(lexicon, AttackSettings(max_candidates=1e12))
    samples = [s for s in generate_corpus(seed=42, samples_per_category=60)
               if s.category == "random"]
    reached = sum(1 for sample in samples if attack.rank(sample.password).covered)
    assert reached == 0


def test_coverage_reports_the_rules_that_did_the_covering(tiny_attack):
    ranks = [tiny_attack.rank(word) for word in ("alpha", "Beta", "epsilon")]
    summary = coverage(ranks)
    assert summary["targets"] == 3
    assert summary["covered"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["rules"] == {"word/capitalized": 1, "word/lower": 1}


# -- schema -----------------------------------------------------------------


def test_the_description_is_publishable(tiny_attack):
    described = tiny_attack.describe()
    assert described["attack_version"] == ATTACK_VERSION
    assert described["universe_size"] == tiny_attack.universe_size
    assert described["rules_placed"] == len(tiny_attack.blocks)
    assert described["fingerprint"].startswith("sha256:")
    assert "shares_evidence" in json.dumps(described)

    # No spelling reaches a report, and the block names are shapes only.
    payload = json.dumps(described)
    for word, _ in TINY_WORDS:
        assert word not in payload


def test_the_rank_serialises_without_the_password(tiny_attack):
    payload = tiny_attack.rank("alpha2001").to_dict()
    assert set(payload) == {"covered", "rank", "log10_rank", "rule"}
    assert "alpha" not in json.dumps(payload)


def test_uncovered_serialises_as_nulls(tiny_attack):
    payload = tiny_attack.rank("epsilon").to_dict()
    assert payload == {"covered": False, "rank": None, "log10_rank": None, "rule": None}


@pytest.mark.parametrize("order", LEXICON_ORDERS)
@pytest.mark.parametrize("rules", RULE_ORDERS)
def test_every_documented_configuration_builds(order: str, rules: str):
    lexicon = Lexicon.build(TINY_WORDS, order=order, seed=7)
    attack = ReferenceAttack.build(
        lexicon, tiny_settings(lexicon_order=order, rule_order=rules)
    )
    assert attack.universe_size > 0
    assert attack.rank("alpha").covered is True


def test_settings_round_trip_through_the_config_schema():
    from indicpass.config import load_config

    settings = AttackSettings.from_config(load_config().password_section("reference_attack"))
    assert settings.lexicon_order in LEXICON_ORDERS
    assert settings.rule_order in RULE_ORDERS
    assert settings.max_candidates > 0
    assert settings.year_range[0] < settings.year_range[1]
    assert settings.max_digits >= 1


# -- the real dictionary ----------------------------------------------------


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_the_lexicon_entries_helper_keeps_only_lower_case_spellings():
    dictionary = build_dictionary(ranked=True)
    entries = dictionary_lexicon_entries(dictionary)
    assert len(entries) == len(FIXTURE_WORDS)
    assert all(word == word.lower() for word, _ in entries)
    assert all(rank is not None for _, rank in entries)


def test_the_fixture_dictionary_produces_a_working_attack():
    dictionary = build_dictionary(ranked=True)
    lexicon = Lexicon.build(dictionary_lexicon_entries(dictionary), order="frequency")
    attack = ReferenceAttack.build(lexicon, AttackSettings(max_candidates=1e12))
    # bharat is the most frequent fixture word and the straight wordlist is the
    # first block, so the attack's very first candidate is this word.
    assert attack.rank("bharat").rank == 1
    # And the capitalised form sits one whole block later, not one position:
    # `word/capitalized` is a separate rule of the same width.
    assert attack.rank("Bharat").rank == len(lexicon) + 1
    assert attack.rank("Bharat2019").covered is True
    assert attack.rank("bharat2019").rule == "word+year/lower"


def test_the_committed_report_pins_a_clean_random_control():
    report = _root() / "results" / "reports" / "reference_attack_hin.json"
    if not report.is_file():  # pragma: no cover - report not generated here
        pytest.skip("Reference-attack report not generated in this checkout.")
    payload = json.loads(report.read_text(encoding="utf-8"))
    control = payload["controls"]["random"]
    assert control["coverage"] <= 0.02, (
        "The reference attack is reaching random strings. Its lexicon is matching "
        "noise and every rank in the report is suspect."
    )
    assert payload["controls"]["reproducibility"]["ranks_match"] is True
    assert payload["controls"]["leakage"]["candidate_generation_uses_pcfg_probabilities"] is False


def test_no_committed_report_pairs_a_sample_id_with_a_password():
    report = _root() / "results" / "reports" / "reference_attack_hin.json"
    if not report.is_file():  # pragma: no cover - report not generated here
        pytest.skip("Reference-attack report not generated in this checkout.")
    payload = json.loads(report.read_text(encoding="utf-8"))
    text = json.dumps(payload)
    for word in ("namaste", "bharat", "krishna", "sharma", "pyaar"):
        for shape in (f'"{word}"', f"{word}123", f"{word}2019"):
            assert shape not in text


def test_the_rule_names_are_shapes_and_not_content(tiny_attack):
    """A rule name is the same class of information as the benchmark's
    ``construction``: how a password was built, never what it says."""
    for block in tiny_attack.blocks:
        assert "/" in block.name
        base, case = block.name.rsplit("/", 1)
        assert case in ("lower", "capitalized", "upper")
        assert base.startswith("word")


def test_the_rule_programme_covers_every_documented_family():
    """The nine families the milestone requires, mapped onto rules."""
    rules = {rule.name for rule in build_rules(AttackSettings(), 1000)}
    for expected in (
        "word/lower",  # single Indic word
        "word+year/lower",  # word + year
        "word+digits3/lower",  # word + number
        "word+word/lower",  # multiple words (and Indic + English)
        "word+symbol/lower",  # word + symbol
        "word/capitalized",  # case variation
        "word/upper",
    ):
        assert expected in rules, expected
    # The remaining two families are not rules: an unseen spelling is a word the
    # lexicon lacks, and a random string is one no rule produces. Both are
    # measured as coverage, which is why neither has an entry here.


def test_every_case_and_suffix_combination_is_present():
    rules = build_rules(AttackSettings(combinator=False), 1000)
    seen = {(rule.case, rule.suffix.name) for rule in rules}
    cases = {"lower", "capitalized", "upper"}
    suffixes = {rule.suffix.name for rule in rules}
    assert seen == set(product(cases, suffixes))


def test_the_real_dictionary_builds_the_configured_attack():
    from indicpass.config import load_config

    config = load_config()
    dictionary_config = config.password_section("dictionary")
    path = config.resolve(dictionary_config["files"]["hin"])
    if not path.is_file():  # pragma: no cover - dictionary not built here
        pytest.skip("IndicDict not built in this checkout.")

    tier_order = [str(tier["name"]) for tier in dictionary_config["tiers"]]
    dictionary = IndicDict.load(path, language="hin", tier_order=tier_order)
    settings = AttackSettings.from_config(config.password_section("reference_attack"))
    lexicon = Lexicon.build(
        dictionary_lexicon_entries(dictionary),
        order=settings.lexicon_order,
        seed=settings.seed,
        size=settings.lexicon_size,
    )
    attack = ReferenceAttack.build(lexicon, settings)
    assert len(lexicon) == len(dictionary)
    assert attack.universe_size <= settings.max_candidates
    assert attack.rank("bharat").covered is True
    assert attack.rank("qwertyuiopasdf").covered is False
