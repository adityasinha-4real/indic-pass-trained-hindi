"""Case transformations: naming them, and what they cost the attacker.

The governing invariant is that capitalising a word must not meaningfully
change its strength. A meter that rewards `Namaste` over `namaste` teaches
people the wrong lesson and overstates their security.
"""

from __future__ import annotations

from indicpass.password.mangling import (
    case_transformation,
    case_variations,
    normalize_for_lookup,
)

# -- naming ----------------------------------------------------------------


def test_lowercase():
    assert case_transformation("namaste") == "lowercase"


def test_capitalized():
    assert case_transformation("Namaste") == "capitalized"


def test_all_uppercase():
    assert case_transformation("NAMASTE") == "uppercase"


def test_trailing_capital():
    assert case_transformation("namastE") == "final_uppercase"


def test_genuinely_mixed_case():
    assert case_transformation("naMaStE") == "mixed_case"


def test_a_token_with_no_letters_reads_as_lowercase():
    """Nothing to vary means a cost of 1, which is what "lowercase" encodes."""
    assert case_transformation("12345") == "lowercase"
    assert case_variations("12345") == 1


def test_a_single_letter_capital_is_capitalized_not_mixed():
    assert case_transformation("A") == "uppercase"


# -- cost ------------------------------------------------------------------


def test_lowercase_costs_nothing_extra():
    assert case_variations("namaste") == 1


def test_capitalising_only_doubles_the_work():
    """The invariant: capitalisation is a factor of 2, not orders of magnitude."""
    assert case_variations("Namaste") == 2


def test_shouting_only_doubles_the_work():
    assert case_variations("NAMASTE") == 2


def test_mixed_case_costs_more_but_stays_bounded():
    mixed = case_variations("naMaStE")
    assert mixed > 2
    # Four orders of magnitude would swamp the dictionary cost entirely; the
    # combinatorial rule keeps a 7-letter word well below that.
    assert mixed < 10_000


def test_case_variations_is_never_zero():
    """It is used as a multiplier, so a zero would erase the dictionary cost."""
    for token in ("", "namaste", "NAMASTE", "naMaStE", "123", "!!!", "aA"):
        assert case_variations(token) >= 1


def test_more_mixing_costs_more_than_less():
    assert case_variations("naMaStE") > case_variations("Namaste")


# -- lookup normalisation --------------------------------------------------


def test_lookup_normalisation_is_lowercasing():
    assert normalize_for_lookup("Namaste") == "namaste"
    assert normalize_for_lookup("NAMASTE") == "namaste"
    assert normalize_for_lookup("namaste") == "namaste"


def test_normalisation_leaves_non_letters_alone():
    assert normalize_for_lookup("namaste123") == "namaste123"
