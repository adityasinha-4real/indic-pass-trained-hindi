"""The out-of-lexicon attack: is the enumeration what it claims to be?

Four things are tested here and they are different in kind.

The **rank arithmetic** is a closed form for a list, so it is checked against
that list: a tiny attack whose whole universe fits in memory is enumerated
candidate by candidate, and every rank the module computes is compared with the
position the candidate actually occupies. Collisions, boundaries, the first
candidate and the last are all in that comparison rather than beside it.

The **counting** is checked the same way: the dynamic programme's answer for how
many candidates exist must equal how many the enumeration emits.

The **bounds** are the attack's definition, so each one is tested by putting a
target just outside it and asserting the result is unreachable *with the right
reason* and no rank.

The **independence** from the estimators is the claim the milestone rests on, so
it is tested four ways -- by parsing the module's imports, by denylisting the
estimator modules, by ranking a corpus with the three estimators replaced by
objects that raise on contact, and by parsing the pipeline script to confirm it
scores every password before it constructs an attack.
"""

from __future__ import annotations

import ast
import json
import math
import sys
from pathlib import Path

import pytest

from conftest import FIXTURE_WORDS, build_dictionary
from indicpass.password.benchmark import generate_corpus
from indicpass.password.character_attack import (
    _PAD,
    _SYMBOL_INDEX,
    ATTACK_VERSION,
    CASES,
    END_OF_STEM,
    MODEL_KINDS,
    STEM_ALPHABET,
    UNREACHABLE_REASONS,
    CharacterAttack,
    CharacterAttackSettings,
    CharacterModel,
    StemCounter,
    SuffixFamily,
    _apply_case,
    _stem_of,
    build_families,
    build_shapes,
    coverage,
    dictionary_stem_corpus,
    quantise,
)

# -- fixtures ---------------------------------------------------------------

#: A training set small enough to reason about and skewed enough that the model
#: is visibly not uniform: ``a`` and ``b`` are common, most letters never occur.
TOY_WORDS: tuple[str, ...] = ("ab", "abc", "ba", "cab", "aa", "bb", "zz", "qi")


def toy_settings(**changes) -> CharacterAttackSettings:
    """Settings whose whole universe can be enumerated in a test.

    ``max_stem_length=2`` is what makes that true: 702 stems, 33 shapes and 24
    suffix members give a universe of about 74,000, which a test can build.
    """
    base = CharacterAttackSettings(
        order=2,
        smoothing=1.0,
        precision=0.5,
        max_candidates=1e9,
        level_ceiling=40,
        min_stem_length=1,
        max_stem_length=2,
        year_range=(2000, 2001),
        symbols="!@",
        max_digits=1,
        max_symbol_digits=1,
    )
    return base if not changes else type(base)(**{**vars(base), **changes})


def toy_model(settings: CharacterAttackSettings | None = None, **changes) -> CharacterModel:
    settings = settings or toy_settings(**changes)
    return CharacterModel.train(
        TOY_WORDS,
        order=settings.order,
        smoothing=settings.smoothing,
        precision=settings.precision,
        kind=settings.model,
        share=settings.training_share,
        seed=settings.training_seed,
    )


@pytest.fixture
def toy_attack() -> CharacterAttack:
    settings = toy_settings()
    return CharacterAttack.build(toy_model(settings), settings)


def stem_level(model: CharacterModel, stem: str) -> int:
    """The stem's level, re-derived test-side from the model's own table.

    Deliberately not :meth:`StemCounter.level_of`: the enumeration below has to
    agree with the counter, and it cannot do that convincingly by calling it.
    """
    width = model.order - 1
    context = _PAD * width
    total = 0
    for character in stem:
        total += model.levels[context][_SYMBOL_INDEX[character]]
        context = (context + character)[-width:] if width else ""
    return total + model.levels[context][_SYMBOL_INDEX[END_OF_STEM]]


def enumerate_attack(attack: CharacterAttack) -> list[str]:
    """Every candidate the attack emits, in order. Test-side and independent.

    Re-derives the ordering from the documented rules -- ascending level, then
    shape index, then stem length and spelling, then suffix index -- rather than
    from anything on the ranking path, so agreeing with it means something.
    """
    model = attack.model
    settings = attack.settings

    stems: dict[int, list[str]] = {}
    candidates = [""]
    for _ in range(settings.max_stem_length):
        candidates = [prefix + character for prefix in candidates for character in STEM_ALPHABET]
        for stem in candidates:
            if len(stem) < settings.min_stem_length:
                continue
            level = stem_level(model, stem)
            if level <= attack.max_level:
                stems.setdefault(level, []).append(stem)
    for group in stems.values():
        group.sort(key=lambda stem: (len(stem), stem))

    emitted: list[str] = []
    for level in range(attack.max_level + 1):
        for shape in attack.shapes:
            remainder = level - shape.level
            if remainder < 0:
                continue
            members = list(shape.family.members())
            assert len(members) == shape.family.size
            for stem in stems.get(remainder, ()):
                surface = _apply_case(stem, shape.case)
                emitted.extend(surface + member for member in members)
    return emitted


@pytest.fixture(scope="module")
def enumerated() -> tuple[CharacterAttack, list[str], dict[str, int]]:
    """The toy attack, its full universe, and where each candidate first lands."""
    settings = toy_settings()
    attack = CharacterAttack.build(toy_model(settings), settings)
    emitted = enumerate_attack(attack)
    first_seen: dict[str, int] = {}
    for position, candidate in enumerate(emitted, start=1):
        first_seen.setdefault(candidate, position)
    return attack, emitted, first_seen


# -- quantisation -----------------------------------------------------------


def test_quantisation_rounds_half_up_not_half_to_even():
    """``round`` is half-to-even, which would make two neighbouring costs land
    differently for no reason a reader could predict."""
    assert quantise(0.125, 0.25) == 1
    assert quantise(0.375, 0.25) == 2
    assert quantise(0.0, 0.25) == 0
    assert quantise(1.0, 0.25) == 4


# -- the character model ----------------------------------------------------


def test_the_model_prices_a_seen_continuation_below_an_unseen_one():
    model = toy_model()
    context = "a"
    seen = model.levels[context][_SYMBOL_INDEX["b"]]
    unseen = model.levels[context][_SYMBOL_INDEX["x"]]
    assert seen < unseen


def test_the_uniform_model_prices_every_symbol_alike():
    model = CharacterModel.train(TOY_WORDS, order=2, precision=0.5, kind="uniform")
    for levels in model.levels.values():
        assert len(set(levels)) == 1
    assert model.training_words == 0


def test_the_model_covers_every_context_a_stem_can_reach():
    """A context the training data never showed still needs a cost; a missing
    entry would be a silent zero instead of a smoothed one."""
    model = toy_model()
    assert len(model.levels) == len(STEM_ALPHABET) + 1  # order 2: "" per letter, plus the pad
    for context in model.levels:
        assert len(model.levels[context]) == len(STEM_ALPHABET) + 1


def test_the_model_does_not_depend_on_the_training_order():
    forwards = CharacterModel.train(TOY_WORDS, order=2, precision=0.5)
    backwards = CharacterModel.train(reversed(TOY_WORDS), order=2, precision=0.5)
    assert forwards.levels == backwards.levels
    assert forwards.fingerprint() == backwards.fingerprint()


def test_a_hold_out_share_trains_on_fewer_words_and_is_deterministic():
    full = CharacterModel.train(TOY_WORDS, order=2, precision=0.5)
    half = CharacterModel.train(TOY_WORDS, order=2, precision=0.5, share=0.5, seed=7)
    again = CharacterModel.train(TOY_WORDS, order=2, precision=0.5, share=0.5, seed=7)
    assert half.training_words < full.training_words
    assert half.fingerprint() == again.fingerprint()
    assert half.fingerprint() != full.fingerprint()


@pytest.mark.parametrize(
    "changes",
    [
        {"order": 0},
        {"smoothing": 0.0},
        {"precision": 0.0},
        {"kind": "by_vibes"},
        {"share": 0.0},
        {"share": 1.5},
    ],
)
def test_an_impossible_model_is_refused(changes):
    with pytest.raises(ValueError):
        CharacterModel.train(TOY_WORDS, **changes)


def test_the_model_description_publishes_no_spelling():
    described = json.dumps(toy_model().describe())
    for word in TOY_WORDS:
        assert f'"{word}"' not in described


def test_the_model_fingerprint_separates_the_kinds():
    prints = {
        kind: CharacterModel.train(TOY_WORDS, order=2, precision=0.5, kind=kind).fingerprint()
        for kind in MODEL_KINDS
    }
    assert len(set(prints.values())) == len(MODEL_KINDS)


# -- suffix families --------------------------------------------------------


def test_suffix_sizes_are_the_stated_arithmetic():
    assert SuffixFamily("", "none").size == 1
    assert SuffixFamily("digits3", "digits", digits=3).size == 1000
    assert SuffixFamily("year", "year", year_range=(1940, 2029)).size == 90
    assert SuffixFamily("symbol", "symbol", symbols="!@#").size == 3
    assert SuffixFamily("s+d2", "symbol_digits", digits=2, symbols="!@").size == 200


def test_every_family_enumerates_exactly_its_size():
    for family in build_families(CharacterAttackSettings()):
        members = list(family.members())
        assert len(members) == family.size
        assert len(set(members)) == family.size
        assert all(len(member) == family.width for member in members)


def test_digit_suffixes_keep_leading_zeros():
    three = SuffixFamily("digits3", "digits", digits=3)
    assert three.split("namaste007") == ("namaste", 7)
    one = SuffixFamily("digits1", "digits", digits=1)
    assert one.split("namaste007") == ("namaste00", 7)


def test_the_year_family_only_matches_inside_its_window():
    years = SuffixFamily("year", "year", year_range=(1940, 2029))
    assert years.split("mera1999") == ("mera", 59)
    assert years.split("mera1899") is None
    assert years.split("mera2030") is None


def test_a_suffix_never_consumes_the_whole_target():
    assert SuffixFamily("digits3", "digits", digits=3).split("123") is None
    assert SuffixFamily("symbol", "symbol", symbols="!").split("!") is None


def test_non_ascii_digits_are_not_digits():
    assert SuffixFamily("digits3", "digits", digits=3).split("mera१२३") is None


# -- shapes -----------------------------------------------------------------


def test_the_case_forms_invert_to_the_stem():
    assert _stem_of("namaste", "lower") == "namaste"
    assert _stem_of("Namaste", "capitalized") == "namaste"
    assert _stem_of("NAMASTE", "upper") == "namaste"
    assert _stem_of("Namaste", "lower") is None
    assert _stem_of("NaMaSte", "capitalized") is None
    assert _stem_of("namast3", "lower") is None
    assert _stem_of("", "lower") is None


def test_a_one_letter_stem_collides_between_capitalized_and_upper():
    """The universe's only genuine ambiguity, and the reason the rank is a
    minimum over shapes rather than the first shape that matches."""
    assert _stem_of("A", "capitalized") == "a"
    assert _stem_of("A", "upper") == "a"
    assert _stem_of("A", "lower") is None


def test_shapes_are_every_case_crossed_with_every_family():
    settings = CharacterAttackSettings()
    shapes = build_shapes(settings)
    assert len(shapes) == len(CASES) * len(build_families(settings))
    assert len({shape.name for shape in shapes}) == len(shapes)
    assert [shape.index for shape in shapes] == list(range(len(shapes)))


def test_shapes_are_ordered_cheapest_family_first_then_lower_case_first():
    shapes = build_shapes(CharacterAttackSettings())
    assert [shape.level for shape in shapes] == sorted(shape.level for shape in shapes)
    assert shapes[0].name == "stem/lower"
    assert [shape.case for shape in shapes[:3]] == list(CASES)


def test_a_bigger_suffix_family_costs_more():
    shapes = {shape.name: shape for shape in build_shapes(CharacterAttackSettings())}
    assert shapes["stem/lower"].level < shapes["stem+digits1/lower"].level
    assert shapes["stem+digits1/lower"].level < shapes["stem+digits5/lower"].level
    assert shapes["stem+year/lower"].level < shapes["stem+digits4/lower"].level


# -- the counting, against ground truth -------------------------------------


def test_the_counter_agrees_with_a_brute_force_count():
    """The dynamic programme is a closed form for a list; here is the list."""
    settings = toy_settings()
    model = toy_model(settings)
    counter = StemCounter(model, min_length=1, max_length=2, max_level=settings.level_ceiling)

    expected: dict[int, int] = {}
    for stem in [*STEM_ALPHABET, *(a + b for a in STEM_ALPHABET for b in STEM_ALPHABET)]:
        level = stem_level(model, stem)
        if level <= settings.level_ceiling:
            expected[level] = expected.get(level, 0) + 1

    for level in range(settings.level_ceiling + 1):
        assert counter.total_at_level(level) == expected.get(level, 0), level
    assert counter.universe == sum(expected.values())


def test_the_counter_places_a_stem_after_exactly_the_stems_that_precede_it():
    settings = toy_settings()
    model = toy_model(settings)
    counter = StemCounter(model, min_length=1, max_length=2, max_level=settings.level_ceiling)

    ordered: dict[int, list[str]] = {}
    for stem in [*STEM_ALPHABET, *(a + b for a in STEM_ALPHABET for b in STEM_ALPHABET)]:
        level = stem_level(model, stem)
        if level <= settings.level_ceiling:
            ordered.setdefault(level, []).append(stem)
    for group in ordered.values():
        group.sort(key=lambda stem: (len(stem), stem))
        for position, stem in enumerate(group):
            assert counter.preceding(stem) == position, stem


def test_the_counter_refuses_to_place_a_stem_outside_its_universe():
    settings = toy_settings()
    counter = StemCounter(toy_model(settings), min_length=1, max_length=2, max_level=40)
    with pytest.raises(ValueError, match="outside the universe"):
        counter.preceding("abc")


def test_the_counter_rejects_impossible_bounds():
    model = toy_model()
    with pytest.raises(ValueError):
        StemCounter(model, min_length=0, max_length=2, max_level=40)
    with pytest.raises(ValueError):
        StemCounter(model, min_length=3, max_length=2, max_level=40)
    with pytest.raises(ValueError):
        StemCounter(model, min_length=1, max_length=2, max_level=0)


def test_a_stem_outside_the_alphabet_or_the_band_has_no_level():
    counter = StemCounter(toy_model(), min_length=1, max_length=2, max_level=40)
    assert counter.level_of("a9") is None
    assert counter.level_of("A") is None
    assert counter.level_of("abc") is None
    assert counter.level_of("") is None


# -- rank arithmetic, against ground truth ----------------------------------


def test_the_counted_universe_is_the_size_of_the_enumerated_one(enumerated):
    attack, emitted, _ = enumerated
    assert len(emitted) == attack.universe_size
    assert attack.universe_size <= attack.settings.max_candidates


def test_every_rank_matches_the_position_in_a_full_enumeration(enumerated):
    """The strongest form of the claim: the arithmetic is checked against the
    list it is a closed form for, candidate by candidate."""
    attack, _, first_seen = enumerated
    assert len(first_seen) > 50_000
    for candidate, expected in first_seen.items():
        observed = attack.rank(candidate)
        assert observed.reachable, candidate
        assert observed.rank == expected, candidate
        assert observed.log10_rank == pytest.approx(math.log10(expected))


def test_the_first_candidate_is_rank_one(enumerated):
    attack, emitted, _ = enumerated
    assert attack.rank(emitted[0]).rank == 1


def test_the_last_candidate_is_the_universe_size(enumerated):
    """The other boundary, and the one an off-by-one in the level offsets would
    move without touching anything in the middle."""
    attack, emitted, first_seen = enumerated
    last = emitted[-1]
    assert first_seen[last] == len(emitted)
    assert attack.rank(last).rank == attack.universe_size


def test_a_colliding_candidate_is_reached_at_its_earliest_reading(enumerated):
    """A one-letter stem is emitted by ``capitalized`` and by ``upper``. Its rank
    must be the first of the two, not the second and not both."""
    attack, emitted, first_seen = enumerated
    duplicated = [
        candidate for candidate, count in _counts(emitted).items() if count > 1
    ]
    assert duplicated, "the toy universe should contain the one-letter case collision"
    for candidate in sorted(duplicated)[:50]:
        assert attack.rank(candidate).rank == first_seen[candidate]
    assert attack.rank("A").shape == "stem/capitalized"


def _counts(values):
    tally: dict[str, int] = {}
    for value in values:
        tally[value] = tally.get(value, 0) + 1
    return tally


def test_a_repeated_character_stem_ranks_like_any_other(enumerated):
    attack, _, first_seen = enumerated
    for candidate in ("aa", "bb", "zz", "AA", "Aa"):
        if candidate in first_seen:
            assert attack.rank(candidate).rank == first_seen[candidate]


def test_the_shortest_stem_is_reachable(enumerated):
    attack, _, _ = enumerated
    assert attack.rank("a").reachable is True


def test_the_longest_stem_is_reachable_and_one_longer_is_not(enumerated):
    attack, _, _ = enumerated
    assert attack.rank("ab").reachable is True
    outside = attack.rank("abc")
    assert outside.reachable is False
    assert outside.rank is None
    assert outside.reason == "stem_too_long"


def test_the_rank_names_the_shape_that_produced_it(enumerated):
    attack, _, _ = enumerated
    assert attack.rank("ab").shape == "stem/lower"
    assert attack.rank("Ab").shape == "stem/capitalized"
    assert attack.rank("AB").shape == "stem/upper"
    assert attack.rank("ab2001").shape == "stem+year/lower"
    assert attack.rank("ab!").shape == "stem+symbol/lower"
    assert attack.rank("ab!7").shape == "stem+symbol+digits1/lower"


def test_a_year_is_reached_by_the_year_shape_not_the_four_digit_shape():
    """Years are a smaller family, so they cost less and the minimum picks them
    -- which is the whole reason a separate year family exists."""
    settings = toy_settings(max_digits=4, max_candidates=1e12)
    attack = CharacterAttack.build(toy_model(settings), settings)
    assert attack.rank("ab2001").shape == "stem+year/lower"
    assert attack.rank("ab3001").shape == "stem+digits4/lower"


# -- the bounds -------------------------------------------------------------


def test_the_empty_password_is_unreachable(toy_attack):
    observed = toy_attack.rank("")
    assert observed.reachable is False
    assert observed.reason == "empty"


@pytest.mark.parametrize(
    ("password", "reason"),
    [
        ("abc", "stem_too_long"),  # the stem band's upper edge
        ("aBc", "no_shape"),  # a capital that is not the first letter
        ("ab2005", "no_shape"),  # a year outside the configured window
        ("ab%", "no_shape"),  # a symbol the attacker does not try
        ("1234", "no_shape"),  # nothing a shape could call a stem
        ("नमस्ते", "no_shape"),  # outside the stem alphabet entirely
    ],
)
def test_a_target_outside_a_bound_is_unreachable_with_that_reason(toy_attack, password, reason):
    observed = toy_attack.rank(password)
    assert observed.reachable is False
    assert observed.reason == reason
    assert observed.reason in UNREACHABLE_REASONS
    assert observed.rank is None
    assert observed.log10_rank is None
    assert observed.shape is None


def test_an_unreachable_target_is_never_given_the_universe_size(toy_attack):
    """The one substitution that would look plausible and destroy the metric."""
    observed = toy_attack.rank("abcdefghij")
    assert observed.rank is None
    assert observed.rank != toy_attack.universe_size


def test_a_stem_priced_above_the_budget_is_unreachable_and_says_so():
    """The budget bound, isolated: the stem is inside the alphabet and inside the
    length band, and only its cost puts it outside.

    The budget is derived from the attack rather than picked, so the test still
    means what it says if the toy model's costs move.
    """
    generous = CharacterAttack.build(toy_model(), toy_settings())
    cheap, dear = generous.rank("ab"), generous.rank("qx")
    assert cheap.level < dear.level, "the toy model should price an unseen bigram higher"

    # Exactly enough to buy every level below the expensive stem's, and no more.
    settings = toy_settings(max_candidates=float(generous.level_offsets[dear.level]))
    frugal = CharacterAttack.build(toy_model(settings), settings)
    assert frugal.max_level == dear.level - 1
    assert frugal.rank("ab").reachable is True
    expensive = frugal.rank("qx")
    assert expensive.reachable is False
    assert expensive.reason == "level_above_budget"
    assert expensive.rank is None


def test_a_smaller_budget_buys_fewer_levels_and_a_smaller_universe():
    generous = CharacterAttack.build(toy_model(), toy_settings())
    settings = toy_settings(max_candidates=1e4)
    frugal = CharacterAttack.build(toy_model(settings), settings)
    assert frugal.max_level < generous.max_level
    assert frugal.universe_size < generous.universe_size
    assert frugal.universe_size <= 1e4


def test_an_unaffordable_budget_is_an_error_not_an_empty_attack():
    with pytest.raises(ValueError, match="No candidate fits"):
        CharacterAttack.build(toy_model(), toy_settings(max_candidates=0.5))


def test_the_build_records_whether_the_budget_or_the_table_bound_the_universe():
    """The toy universe is smaller than the toy budget, so the counting table --
    not the budget -- ends its enumeration. That has to be visible in the report,
    because a universe bounded by an implementation detail is not a budget."""
    bound_by_table = CharacterAttack.build(toy_model(), toy_settings())
    assert bound_by_table.universe_size < bound_by_table.settings.max_candidates
    assert bound_by_table.max_level == bound_by_table.settings.level_ceiling
    assert bound_by_table.budget_binding is False

    settings = toy_settings(max_candidates=1e4)
    bound_by_budget = CharacterAttack.build(toy_model(settings), settings)
    assert bound_by_budget.max_level < settings.level_ceiling
    assert bound_by_budget.budget_binding is True


def test_a_model_fitted_with_other_settings_is_refused():
    with pytest.raises(ValueError, match="different settings"):
        CharacterAttack.build(toy_model(toy_settings(order=2)), toy_settings(order=3))


# -- out-of-lexicon reach ---------------------------------------------------


def test_a_spelling_absent_from_the_training_data_is_still_reachable():
    """The whole point of the milestone. ``qi`` is in the toy training set and
    ``qx`` is not, and both are in the universe -- the second just costs more."""
    settings = toy_settings(max_candidates=1e9)
    attack = CharacterAttack.build(toy_model(settings), settings)
    seen = attack.rank("ab")
    unseen = attack.rank("xk")
    assert seen.reachable and unseen.reachable
    assert unseen.rank > seen.rank


def test_the_trained_model_ranks_language_shaped_stems_ahead_of_unlikely_ones():
    """A character model that carries no information would order these the same.

    This is the property the whole validation depends on, so it is asserted on
    the fixture dictionary rather than only observed in the report.
    """
    dictionary = build_dictionary(ranked=True)
    words = dictionary_stem_corpus(dictionary)
    settings = CharacterAttackSettings(order=2, precision=0.5, max_stem_length=8)
    attack = CharacterAttack.build(
        CharacterModel.train(words, order=2, precision=0.5), settings
    )
    # `namaste` is a training word; `bharat` is one; `qxzjkv` is nothing.
    shaped = attack.rank("namaste")
    noise = attack.rank("qxzjkv")
    assert shaped.reachable
    assert not noise.reachable or noise.rank > shaped.rank


def test_the_uniform_model_orders_by_length_alone():
    """The null arm's defining property: with no character statistics every stem
    of a length costs the same, so the ordering is length then spelling."""
    settings = toy_settings(model="uniform")
    attack = CharacterAttack.build(toy_model(settings), settings)
    assert attack.rank("aa").rank < attack.rank("ab").rank < attack.rank("zz").rank
    assert attack.rank("z").rank < attack.rank("aa").rank


# -- determinism ------------------------------------------------------------


def test_two_builds_agree_on_the_fingerprint_and_on_every_rank():
    first = CharacterAttack.build(toy_model(), toy_settings())
    second = CharacterAttack.build(toy_model(), toy_settings())
    assert first.fingerprint() == second.fingerprint()
    candidates = enumerate_attack(first)[:2000]
    assert [first.rank(c).rank for c in candidates] == [second.rank(c).rank for c in candidates]


def test_the_fingerprint_moves_when_the_attack_does():
    base = CharacterAttack.build(toy_model(), toy_settings()).fingerprint()
    for change in (
        {"model": "uniform"},
        {"order": 3},
        {"smoothing": 0.1},
        {"precision": 0.25},
        {"max_candidates": 1e5},
        {"max_stem_length": 3},
        {"symbols": "!"},
        {"year_range": (2000, 2010)},
    ):
        settings = toy_settings(**change)
        moved = CharacterAttack.build(toy_model(settings), settings).fingerprint()
        assert moved != base, change


def test_ranking_holds_no_state_between_calls(toy_attack):
    once = toy_attack.rank("ab2001")
    for _ in range(5):
        toy_attack.rank("ba!7")
    assert toy_attack.rank("ab2001") == once


def test_the_memo_cannot_change_an_answer(toy_attack):
    """The counter memoises stem positions. A memo that changed a result would
    make a rank depend on what was ranked before it."""
    cold = toy_attack.rank("zz").rank
    for _ in range(3):
        assert toy_attack.rank("zz").rank == cold


# -- independence from the estimators ---------------------------------------

#: Modules whose appearance in the attack's imports would make the validation
#: circular. The leakage safeguard, in the only form a test can check
#: mechanically.
FORBIDDEN_IMPORTS = (
    "indicpass.password.meter",
    "indicpass.password.scoring",
    "indicpass.password.matcher",
    "indicpass.password.baseline",
    "indicpass.password.pcfg",
    "indicpass.password.experiment",
    "indicpass.password.validation",
    "indicpass.password.reference_attack",
    "zxcvbn",
)


def attack_module_imports() -> set[str]:
    """Every module ``character_attack.py`` imports, from its AST.

    Parsed, not grepped: a comment mentioning the PCFG must not fail the checks
    below, and an import hidden inside a function must not pass them.
    """
    source = Path(
        __import__("indicpass.password.character_attack", fromlist=["x"]).__file__
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
            f"character_attack.py imports {name!r}. Deriving the attack ordering from "
            "an estimator would make the validation circular."
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
        f"character_attack.py imports {sorted(outside)}. The attack must depend on "
        "nothing that could carry an estimator's output into the candidate ordering."
    )


class Exploding:
    """Raises on any contact. Stands in for the three estimators."""

    def __getattr__(self, name: str):  # pragma: no cover - the point is to raise
        raise AssertionError(
            f"The character attack touched an estimator ({name}). Candidate "
            "generation must not depend on any estimator's output."
        )

    def __call__(self, *args, **kwargs):  # pragma: no cover - the point is to raise
        raise AssertionError("The character attack called an estimator.")


def test_ranking_a_corpus_never_touches_an_estimator(monkeypatch):
    """The dynamic half of the leakage check: same ranks with the estimators
    replaced by objects that raise on contact."""
    import indicpass.password.baseline as baseline_module
    import indicpass.password.meter as meter_module
    import indicpass.password.pcfg.estimator as pcfg_module

    attack = CharacterAttack.build(toy_model(), toy_settings())
    samples = generate_corpus(seed=42, samples_per_category=5)
    before = [attack.rank(sample.password).rank for sample in samples]

    monkeypatch.setattr(meter_module, "IndicPassMeter", Exploding())
    monkeypatch.setattr(pcfg_module, "PcfgEstimator", Exploding())
    monkeypatch.setattr(baseline_module, "load_baseline", Exploding())

    rebuilt = CharacterAttack.build(toy_model(), toy_settings())
    after = [rebuilt.rank(sample.password).rank for sample in samples]
    assert after == before


def test_the_training_corpus_helper_reads_only_spellings():
    """A frequency, a rank or a tier reaching the model would put an estimator's
    evidence into the ordering by the back door."""
    dictionary = build_dictionary(ranked=True)
    words = dictionary_stem_corpus(dictionary)
    assert sorted(words) == sorted(word for word, _, _ in FIXTURE_WORDS)
    assert all(isinstance(word, str) for word in words)


def _pipeline_source() -> str:
    root = Path(__file__).resolve().parents[1]
    return (root / "scripts" / "milestone5_oov_attack.py").read_text(encoding="utf-8")


def test_the_pipeline_scores_every_password_before_any_attack_exists():
    """Order of operations, asserted rather than trusted.

    If an attack object were built first, an estimator could in principle be
    handed something derived from it. The script is written so that cannot
    happen; this parses ``main`` and checks that it is still true.
    """
    tree = ast.parse(_pipeline_source())
    main = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "main"
    )
    calls = [
        (node.func.id, node.lineno)
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    ]
    attributes = [
        (f"{node.func.value.id}.{node.func.attr}", node.lineno)
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
    ]
    scoring = min(line for name, line in calls if name == "score_predictions")
    building = min(line for name, line in attributes if name == "CharacterAttack.build")
    assert scoring < building, (
        "milestone5_oov_attack.py constructs an attack before it scores the corpus. "
        "The estimators must not be able to see the attack they are validated against."
    )


def test_the_pipeline_reuses_one_scoring_pass_across_every_arm():
    """A second scoring pass inside the arm loop would let an arm's attack change
    what the estimators said."""
    source = _pipeline_source()
    assert source.count("score_predictions(meter, samples)") == 1


# -- publishability ---------------------------------------------------------


def test_the_description_is_publishable(toy_attack):
    described = toy_attack.describe()
    assert described["attack_version"] == ATTACK_VERSION
    assert described["universe_size"] == toy_attack.universe_size
    assert described["max_level"] == toy_attack.max_level
    assert described["fingerprint"].startswith("sha256:")
    payload = json.dumps(described)
    assert "shares_evidence" in payload
    assert "unreachable != universe_size" in payload
    for word in TOY_WORDS:
        assert f'"{word}"' not in payload


def test_the_description_states_every_search_dimension_and_bound(toy_attack):
    described = toy_attack.describe()
    assert set(described["search_dimensions"]) == {"stem", "case", "suffix", "budget"}
    assert len(described["ordering"]) == 4
    assert len(described["assumptions"]) >= 4


def test_the_rank_serialises_without_the_password(toy_attack):
    payload = toy_attack.rank("zq2001").to_dict()
    assert set(payload) == {"reachable", "rank", "log10_rank", "shape", "level", "reason"}
    assert "zq" not in json.dumps(payload)
    assert "2001" not in json.dumps(payload)


def test_unreachable_serialises_as_nulls_plus_a_reason(toy_attack):
    payload = toy_attack.rank("abcdef").to_dict()
    assert payload["rank"] is None
    assert payload["log10_rank"] is None
    assert payload["shape"] is None
    assert payload["reason"] in UNREACHABLE_REASONS


def test_the_shape_names_are_forms_and_not_content(toy_attack):
    for shape in toy_attack.shapes:
        assert "/" in shape.name
        base, case = shape.name.rsplit("/", 1)
        assert case in CASES
        assert base.startswith("stem")


def test_coverage_reports_the_shapes_and_the_reasons(toy_attack):
    ranks = [toy_attack.rank(word) for word in ("ab", "Ba", "abcdef")]
    summary = coverage(ranks)
    assert summary["targets"] == 3
    assert summary["reachable"] == 2
    assert summary["coverage"] == pytest.approx(2 / 3, abs=1e-4)
    assert summary["shapes"] == {"stem/capitalized": 1, "stem/lower": 1}
    assert summary["reasons"] == {"stem_too_long": 1}


def test_coverage_of_nothing_is_not_a_division_by_zero():
    assert coverage([])["coverage"] == 0.0


# -- configuration ----------------------------------------------------------


def test_settings_round_trip_through_the_config_schema():
    from indicpass.config import load_config

    settings = CharacterAttackSettings.from_config(
        load_config().password_section("character_attack")
    )
    assert settings.model in MODEL_KINDS
    assert settings.order >= 1
    assert settings.precision > 0
    assert settings.max_candidates > 0
    assert 1 <= settings.min_stem_length <= settings.max_stem_length
    assert settings.year_range[0] < settings.year_range[1]


def test_the_shipped_budget_matches_the_reference_attack():
    """Milestone 5 spends what Milestone 4 spent, on purpose: the difference in
    their coverage has to be a statement about the candidate model, not about
    how long each attacker was allowed to run."""
    from indicpass.config import load_config

    config = load_config()
    milestone4 = config.password_section("reference_attack")["max_candidates"]
    milestone5 = config.password_section("character_attack")["max_candidates"]
    assert float(milestone5) == float(milestone4)


@pytest.mark.parametrize("kind", MODEL_KINDS)
def test_every_documented_model_kind_builds(kind: str):
    settings = toy_settings(model=kind)
    attack = CharacterAttack.build(toy_model(settings), settings)
    assert attack.universe_size > 0
    assert attack.rank("ab").reachable is True


# -- the real dictionary ----------------------------------------------------


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_the_real_dictionary_builds_the_configured_attack():
    from indicpass.config import load_config
    from indicpass.password.dictionary import IndicDict

    config = load_config()
    dictionary_config = config.password_section("dictionary")
    path = config.resolve(dictionary_config["files"]["hin"])
    if not path.is_file():  # pragma: no cover - dictionary not built here
        pytest.skip("IndicDict not built in this checkout.")

    tier_order = [str(tier["name"]) for tier in dictionary_config["tiers"]]
    dictionary = IndicDict.load(path, language="hin", tier_order=tier_order)
    settings = CharacterAttackSettings.from_config(
        config.password_section("character_attack")
    )
    words = dictionary_stem_corpus(dictionary)
    attack = CharacterAttack.build(
        CharacterModel.train(
            words,
            order=settings.order,
            smoothing=settings.smoothing,
            precision=settings.precision,
            kind=settings.model,
        ),
        settings,
    )
    assert attack.universe_size <= settings.max_candidates
    assert attack.budget_binding is True
    # The claim the milestone exists to test: a Romanized Hindi spelling the
    # dictionary does NOT contain is still in this attack's universe.
    assert "namaste" not in dictionary
    assert attack.rank("namaste").reachable is True
    assert attack.rank("namaste2019").reachable is True


def test_the_committed_report_is_internally_consistent():
    report = _root() / "results" / "reports" / "milestone5_oov_attack.json"
    if not report.is_file():  # pragma: no cover - report not generated here
        pytest.skip("Milestone 5 report not generated in this checkout.")
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["reproducibility"]["byte_identical"] is True
    assert payload["controls"]["leakage"]["candidate_generation_uses_pcfg_probabilities"] is False
    assert payload["attack"]["budget_binding"] is True

    # No target is ever both unreachable and ranked, in either direction.
    for row in payload["targets"]:
        if row["reachable"]:
            assert row["attack_rank"] is not None
            assert row["attack_rank"] <= payload["attack"]["universe_size"]
            assert row["exclusion_reason"] is None
        else:
            assert row["attack_rank"] is None
            assert row["exclusion_reason"] in UNREACHABLE_REASONS


def test_no_committed_report_pairs_a_sample_id_with_a_password():
    report = _root() / "results" / "reports" / "milestone5_oov_attack.json"
    if not report.is_file():  # pragma: no cover - report not generated here
        pytest.skip("Milestone 5 report not generated in this checkout.")
    text = report.read_text(encoding="utf-8")
    for word in ("namaste", "bharat", "krishna", "sharma", "pyaar"):
        for shape in (f'"{word}"', f"{word}123", f"{word}2019"):
            assert shape not in text
