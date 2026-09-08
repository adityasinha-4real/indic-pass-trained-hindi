"""Non-lexical spans: digits, years, symbols, repeats, and unexplained text.

The dictionary explains the interesting part of a password. These patterns
explain the rest, and their cost model is what keeps ``namaste123`` from
scoring like a random ten-character string.

Every function returns a guess count for one span, and every one is derived
from a stated attacker behaviour rather than from a character-count formula:

* **digits** -- the attacker enumerates all *d*-digit strings: ``10**d``.
* **year** -- a four-digit run inside a plausible year window is enumerated
  from that window, ~136 values instead of 10,000. This is why ``sharma2024``
  is weaker than ``sharma8317``, which is the whole point of having the case.
* **symbols** -- ``|S|**s`` over the assumed symbol alphabet.
* **repeat** -- one character choice plus the run length, not ``C**n``:
  ``aaaaaa`` is not a six-character random string.
* **bruteforce** -- a span nothing explained. Cardinality comes from
  configuration; see :func:`bruteforce_guesses`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

__all__ = [
    "SYMBOL_CHARACTERS",
    "bruteforce_log10_guesses",
    "character_classes",
    "describe_run",
    "digit_log10_guesses",
    "is_digits",
    "is_symbols",
    "is_year",
    "observed_cardinality",
    "repeat_guesses",
    "symbol_log10_guesses",
    "year_guesses",
]

#: What counts as a symbol. Printable ASCII that is neither a letter nor a
#: digit nor a space -- the 33 characters a password policy means by "special".
SYMBOL_CHARACTERS = frozenset("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


def is_digits(token: str) -> bool:
    return bool(token) and all(char.isdigit() and char.isascii() for char in token)


def is_symbols(token: str) -> bool:
    return bool(token) and all(char in SYMBOL_CHARACTERS for char in token)


def is_year(token: str, year_range: tuple[int, int]) -> bool:
    """True for a 4-digit run falling inside the configured year window."""
    if len(token) != 4 or not is_digits(token):
        return False
    low, high = year_range
    return low <= int(token) <= high


def year_guesses(year_range: tuple[int, int]) -> float:
    """Enumerate the year window. Independent of which year it is."""
    low, high = year_range
    return float(max(high - low + 1, 1))


def repeat_guesses(token: str, *, cardinality: int) -> float:
    """A run of one repeated character.

    The attacker picks the character, then the length: ``cardinality * length``.
    Not ``cardinality ** length`` -- treating ``aaaa`` as four independent
    choices is precisely the over-estimate this pattern exists to prevent.
    """
    return float(max(cardinality, 1) * max(len(token), 1))


def character_classes(text: str) -> set[str]:
    """Which of lowercase / uppercase / digits / symbols appear in *text*."""
    present: set[str] = set()
    for char in text:
        if char.islower():
            present.add("lowercase")
        elif char.isupper():
            present.add("uppercase")
        elif char.isdigit():
            present.add("digits")
        elif char in SYMBOL_CHARACTERS:
            present.add("symbols")
        else:
            # Whitespace, accented letters, anything else. Counted as symbols
            # rather than ignored, so it cannot make a password look cheaper.
            present.add("symbols")
    return present


def observed_cardinality(text: str, sizes: Mapping[str, int]) -> int:
    """Alphabet size implied by the character classes present in *text*.

    At least 1, so an empty string cannot produce a zero-cardinality span.
    """
    return max(sum(int(sizes.get(name, 0)) for name in character_classes(text)), 1)


def bruteforce_log10_guesses(token: str, *, cardinality: int) -> float:
    """Cost of a span the meter could not explain: ``cardinality ** length``.

    Returned as a **logarithm**: ``26 ** 200`` is a real cost for a real (if
    silly) password, and one that no float can hold. ``length * log10(c)`` is
    exact and cannot overflow.

    *cardinality* is resolved by the caller from
    ``scoring.bruteforce_cardinality``. With the default ``observed`` setting
    it is the alphabet implied by the whole password, which is the classical
    model. Note in any published comparison that zxcvbn instead uses a flat 10
    per character; that makes zxcvbn read lower than IndicPass on genuinely
    random strings for reasons unrelated to the Indic lexicon.
    """
    return len(token) * math.log10(max(cardinality, 1))


def symbol_log10_guesses(token: str, *, alphabet_size: int) -> float:
    """As :func:`bruteforce_log10_guesses`, for a run of symbols."""
    return len(token) * math.log10(max(alphabet_size, 1))


def digit_log10_guesses(token: str, *, digits_per_position: int) -> float:
    """As :func:`bruteforce_log10_guesses`, for a run of digits."""
    return len(token) * math.log10(max(digits_per_position, 1))


def describe_run(token: str) -> dict[str, Any]:
    """Shape-only description of a span, safe to serialise.

    Deliberately returns nothing that could reconstruct the characters -- just
    the length and which classes were involved.
    """
    return {"length": len(token), "classes": sorted(character_classes(token))}
