"""Find every recognisable span inside a password, and say how good it is.

The matcher answers one question: *which substrings of this password does
IndicPass have an explanation for?* It does not decide which explanation wins
-- that is :mod:`indicpass.password.scoring`, which picks the cheapest way to
cover the whole password out of everything found here.

Three properties matter.

**Matches are substrings, never only the whole password.** ``namaste123`` is not
in any dictionary and never will be; ``namaste`` is. So the scan is over spans,
which is what makes ``sharma@123`` decompose into a name, a symbol and a digit
run instead of failing to a single unexplained blob.

**A dictionary hit is exact.** A span matches only if its lower-cased form is
literally a key in IndicDict. Being made of Latin letters is not enough --
``xkcd`` is a run of valid characters and must not become an Indic match
because of it.

**Not every hit is equally good evidence.** This is what Milestone 2 added, and
it is not cosmetic. Measured against the real 298k-entry dictionary:

===========  ==========  ================================================
token length  entries     P(a random lower-case string of that length is a key)
===========  ==========  ================================================
3             6,999       0.398
4             24,967      0.055
5             65,834      0.0055
6             70,278      0.00023
7             29,925      0.0000037
===========  ==========  ================================================

Two of every five three-letter strings are in the dictionary, and 95% of random
ten-character strings contain *some* key. A three-letter hit is therefore
close to no evidence at all, while a seven-letter hit is strong evidence. The
:class:`MatchClass` a hit is given, and the penalty attached to it, exist to
keep that difference visible to the guess model instead of pricing an accident
and a word identically.

The class boundaries and penalties are **configuration, calibrated by
experiment** -- see ``results/reports/guess_model_sensitivity.md`` for the sweep
that chose them and what changing them does.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from indicpass.password.dictionary import IndicDict
from indicpass.password.mangling import (
    case_transformation,
    case_variations,
    normalize_for_lookup,
)
from indicpass.password.patterns import (
    describe_run,
    digit_log10_guesses,
    is_digits,
    is_symbols,
    is_year,
    repeat_guesses,
    symbol_log10_guesses,
    year_guesses,
)
from indicpass.password.result import Match

__all__ = ["MatchClass", "MatcherSettings", "PasswordMatcher"]


class MatchClass(StrEnum):
    """How much of the password a dictionary hit explains, and how cleanly.

    Ordered from strongest evidence to weakest. The distinction is between a
    password that *is* a word and one that merely *contains* a string some
    wordlist happens to hold.
    """

    #: The hit covers the whole password, as written.
    EXACT_WORD = "exact_word"
    #: The hit covers the whole password once a case change is undone.
    TRANSFORMED_WORD = "transformed_word"
    #: A proper substring, long enough that a coincidence is unlikely.
    SUBSTRING_WORD = "substring_word"
    #: A proper substring short enough to turn up by chance.
    FRAGMENT = "fragment"


@dataclass(frozen=True)
class MatcherSettings:
    """Everything the matcher reads from ``config/password.yaml``."""

    #: Shortest dictionary entry that may match at all, anywhere.
    min_word_length: int
    #: Shortest *proper substring* hit still treated as a real word. Below
    #: this a hit is a :attr:`MatchClass.FRAGMENT`.
    min_substring_length: int
    max_match_length: int
    #: Offer proper-substring hits at all. Off, only whole-password matches
    #: are produced -- the "exact only" arm of the ablation.
    allow_substring_matches: bool
    #: Offer hits below ``min_substring_length``. Off, they are dropped rather
    #: than penalised.
    allow_fragment_matches: bool
    #: Multiplier applied to a hit's guess cost, per :class:`MatchClass`.
    #: 1.0 leaves the cost as the wordlist position alone.
    class_penalties: Mapping[str, float]

    digits_per_position: int
    year_range: tuple[int, int]
    symbol_alphabet_size: int
    repeat_cardinality: int

    @classmethod
    def from_config(
        cls, matching: Mapping[str, Any], scoring: Mapping[str, Any]
    ) -> MatcherSettings:
        low, high = tuple(scoring.get("year_range", (1900, 2035)))
        sizes = scoring.get("character_class_sizes") or {}
        penalties = {
            str(name): float(value)
            for name, value in (matching.get("class_penalties") or {}).items()
        }
        return cls(
            min_word_length=int(matching.get("min_word_length", 3)),
            min_substring_length=int(matching.get("min_substring_length", 4)),
            max_match_length=int(matching.get("max_match_length", 24)),
            allow_substring_matches=bool(matching.get("allow_substring_matches", True)),
            allow_fragment_matches=bool(matching.get("allow_fragment_matches", True)),
            class_penalties=penalties,
            digits_per_position=int(scoring.get("digits_per_position", 10)),
            year_range=(int(low), int(high)),
            symbol_alphabet_size=int(scoring.get("symbol_alphabet_size", 33)),
            # A repeated character is drawn from the lower-case alphabet unless
            # something better is known; only the run length varies after that.
            repeat_cardinality=int(sizes.get("lowercase", 26)),
        )

    def penalty_for(self, match_class: MatchClass) -> float:
        """Cost multiplier for *match_class*. Missing means 1.0: no correction."""
        return float(self.class_penalties.get(str(match_class), 1.0))


class PasswordMatcher:
    """Scans a password for dictionary hits and structural patterns."""

    def __init__(
        self,
        dictionaries: Sequence[IndicDict],
        settings: MatcherSettings,
        *,
        named_entity_tiers: Iterable[str] = (),
    ) -> None:
        self.dictionaries = list(dictionaries)
        self.settings = settings
        self.named_entity_tiers = frozenset(named_entity_tiers)

    # -- the scan ----------------------------------------------------------

    def matches(self, password: str) -> list[Match]:
        """Every match found, in no particular order."""
        found: list[Match] = []
        found.extend(self._dictionary_matches(password))
        found.extend(self._run_matches(password))
        found.extend(self._repeat_matches(password))
        return found

    # -- dictionary --------------------------------------------------------

    def classify(self, token: str, *, whole_password: bool) -> MatchClass:
        """Which :class:`MatchClass` a hit on *token* belongs to."""
        if whole_password:
            if case_transformation(token) == "lowercase":
                return MatchClass.EXACT_WORD
            return MatchClass.TRANSFORMED_WORD
        if len(token) >= self.settings.min_substring_length:
            return MatchClass.SUBSTRING_WORD
        return MatchClass.FRAGMENT

    def _admits(self, match_class: MatchClass) -> bool:
        if match_class is MatchClass.SUBSTRING_WORD:
            return self.settings.allow_substring_matches
        if match_class is MatchClass.FRAGMENT:
            return self.settings.allow_substring_matches and (
                self.settings.allow_fragment_matches
            )
        return True

    def _dictionary_matches(self, password: str) -> list[Match]:
        length = len(password)
        low = max(self.settings.min_word_length, 1)
        high = min(self.settings.max_match_length, length)

        found: list[Match] = []
        for start in range(length):
            for end in range(start + low, min(start + high, length) + 1):
                token = password[start:end]
                if not token.isalpha():
                    # A dictionary word is letters. Skipping early keeps the
                    # O(L^2) scan from doing a lookup per digit run.
                    continue

                match_class = self.classify(
                    token, whole_password=(start == 0 and end == length)
                )
                if not self._admits(match_class):
                    continue

                key = normalize_for_lookup(token)
                for dictionary in self.dictionaries:
                    entry = dictionary.get(key)
                    if entry is None:
                        continue
                    found.append(
                        self._build_match(dictionary, entry, token, start, end, match_class)
                    )
                    break  # first dictionary wins; they are searched in order
        return found

    def _build_match(
        self,
        dictionary: IndicDict,
        entry: Any,
        token: str,
        start: int,
        end: int,
        match_class: MatchClass,
    ) -> Match:
        position = dictionary.guess_position(entry)
        tier = dictionary.tier_of(entry)
        variations = case_variations(token)
        penalty = self.settings.penalty_for(match_class)

        return Match.from_guesses(
            "indic_word",
            start,
            end,
            token,
            # Reach the word in the attacker's wordlist, undo the case change,
            # then correct for how much the hit actually explains. Three
            # independent costs, so they multiply.
            position.position * variations * penalty,
            {
                "language": dictionary.language,
                "match_class": str(match_class),
                "class_penalty": penalty,
                # Which pricing policy produced the position, so no report has
                # to guess whether a number rests on evidence or on a fallback.
                "rank_policy": position.policy,
                "wordlist_position": round(position.position, 2),
                "tier": tier.name,
                "tier_size": tier.size,
                "tier_offset": tier.offset,
                "native_form": entry.native_form,
                "model_verified": entry.model_verified,
                "case_transformation": case_transformation(token),
                "case_variations": variations,
                "is_named_entity": tier.name in self.named_entity_tiers,
                # The observed values, or an explicit absence. Never a
                # substituted average -- see indicpass.password.frequency.
                "frequency": entry.frequency,
                "rank": entry.rank,
                "frequency_source": entry.frequency_source,
            },
        )

    # -- digits, years, symbols --------------------------------------------

    def _run_matches(self, password: str) -> list[Match]:
        """Digit, year and symbol spans.

        Every sub-span of a maximal run is offered, not just the run itself.
        That is what lets ``krishna19999`` be read as a year followed by a
        stray digit if that turns out cheaper than one five-digit run.
        """
        found: list[Match] = []
        for start, end in _maximal_runs(password, is_digits):
            for i in range(start, end):
                for j in range(i + 1, end + 1):
                    token = password[i:j]
                    found.append(
                        Match(
                            pattern="digits",
                            start=i,
                            end=j,
                            token=token,
                            cost=digit_log10_guesses(
                                token, digits_per_position=self.settings.digits_per_position
                            ),
                            detail={"length": len(token)},
                        )
                    )
                    if is_year(token, self.settings.year_range):
                        found.append(
                            Match.from_guesses(
                                "year",
                                i,
                                j,
                                token,
                                year_guesses(self.settings.year_range),
                                {"year_range": list(self.settings.year_range)},
                            )
                        )

        for start, end in _maximal_runs(password, is_symbols):
            for i in range(start, end):
                for j in range(i + 1, end + 1):
                    token = password[i:j]
                    found.append(
                        Match(
                            pattern="symbols",
                            start=i,
                            end=j,
                            token=token,
                            cost=symbol_log10_guesses(
                                token, alphabet_size=self.settings.symbol_alphabet_size
                            ),
                            detail={"length": len(token)},
                        )
                    )
        return found

    # -- repeats -----------------------------------------------------------

    def _repeat_matches(self, password: str) -> list[Match]:
        """Runs of three or more identical characters.

        Three, not two: ``ll`` in ``hello`` is a fact about Hindi and English
        spelling, not a password pattern, and matching it would hand out a
        discount on ordinary words.
        """
        found: list[Match] = []
        start = 0
        while start < len(password):
            end = start + 1
            while end < len(password) and password[end] == password[start]:
                end += 1
            if end - start >= 3:
                token = password[start:end]
                found.append(
                    Match.from_guesses(
                        "repeat",
                        start,
                        end,
                        token,
                        repeat_guesses(token, cardinality=self.settings.repeat_cardinality),
                        {"repeat_length": len(token), **describe_run(token)},
                    )
                )
            start = end
        return found


def _maximal_runs(text: str, predicate) -> list[tuple[int, int]]:
    """Half-open spans of the longest runs where every character satisfies *predicate*."""
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for index, char in enumerate(text):
        if predicate(char):
            if start is None:
                start = index
        elif start is not None:
            runs.append((start, index))
            start = None
    if start is not None:
        runs.append((start, len(text)))
    return runs
