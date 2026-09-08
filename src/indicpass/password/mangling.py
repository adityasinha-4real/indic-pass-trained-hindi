"""Transformations a person applies to a word before using it as a password.

Milestone 1 models **case only**. A dictionary holds ``namaste``; people type
``Namaste``, ``NAMASTE``, ``naMaSte``. Undoing the transformation is what lets
the matcher find the word; counting how many transformations the attacker must
try is what turns that into guesses.

The cost rule is deliberately the same combinatorial rule zxcvbn uses:

* all lower case              -> 1 variation
* Capitalised, ALL UPPER, or
  trailing capital            -> 2 variations
* anything else               -> sum of C(n, i) for i = 1..min(uppers, lowers)

Two reasons. First, it satisfies the invariant that capitalising a word must
not meaningfully change its strength -- ``Namaste`` costs twice ``namaste``,
not a thousand times. Second, and more important for the experiment: holding
the case model identical to the baseline's means any difference the Milestone 2
comparison finds is attributable to the **lexicon**, not to two estimators
disagreeing about capital letters.

Leet substitution (``n4m4ste``), separators and repeats are Milestone 3. They
are listed as limitations in ``docs/password_strength_design.md`` rather than
half-implemented here.
"""

from __future__ import annotations

from math import comb

__all__ = [
    "CASE_TRANSFORMATIONS",
    "case_transformation",
    "case_variations",
    "normalize_for_lookup",
]

#: Every label :func:`case_transformation` can return. Ordered by how much work
#: undoing it costs the attacker.
CASE_TRANSFORMATIONS: tuple[str, ...] = (
    "lowercase",
    "capitalized",
    "uppercase",
    "final_uppercase",
    "mixed_case",
)


def normalize_for_lookup(token: str) -> str:
    """The form a token is looked up in the dictionary as.

    Lower-casing only. The dictionary was built from a corpus whose source side
    was already lower-cased at preprocessing time, so this is the same
    normalisation on both sides of the lookup.
    """
    return token.lower()


def case_transformation(token: str) -> str:
    """Name the case pattern of *token*.

    A token with no cased letters at all reads as ``"lowercase"``: there is
    nothing for an attacker to vary, which is exactly what a cost of 1 means.
    """
    letters = [char for char in token if char.isalpha()]
    if not letters:
        return "lowercase"

    uppers = sum(1 for char in letters if char.isupper())
    if uppers == 0:
        return "lowercase"
    if uppers == len(letters):
        return "uppercase"
    if uppers == 1 and letters[0].isupper():
        return "capitalized"
    if uppers == 1 and letters[-1].isupper():
        return "final_uppercase"
    return "mixed_case"


def case_variations(token: str) -> int:
    """How many case variants an attacker must try to reach *token*.

    Always at least 1, so it is safe to use as a multiplier.
    """
    uppers = sum(1 for char in token if char.isupper())
    lowers = sum(1 for char in token if char.islower())

    if uppers == 0:
        return 1
    if case_transformation(token) in {"capitalized", "uppercase", "final_uppercase"}:
        # The three patterns people actually use. An attacker tries the word
        # as-is and then the obvious shift; that is two attempts, not a
        # combinatorial explosion.
        return 2

    # Genuinely mixed case: the attacker must choose which of the letters are
    # capitalised. Summing only to min(uppers, lowers) counts each arrangement
    # once whichever side is in the minority.
    total = uppers + lowers
    return sum(comb(total, index) for index in range(1, min(uppers, lowers) + 1)) or 1
