"""The reference attack: a bounded enumeration whose ranks are *observed*.

Milestones 2 and 3 produced three estimators and no way to tell which of them
is right. Every comparison so far has been between models; this module supplies
the first quantity in the project that is not a model output at all.

    observed rank -- the position at which a specific, fully specified attacker
                     produces a specific password.

That is a fact about the attack, computable exactly, and it is what the three
estimators are scored against. It is NOT a fact about real attackers, and the
distinction is the whole reason this module is written the way it is.

The attack
----------
The standard offline attack is a wordlist run through an ordered rule set --
hashcat, John the Ripper, and every published cracking study work this way. So:

* a **lexicon**: Romanized spellings from IndicDict, in a documented order;
* a **rule programme**: an ordered list of transformations, each a bounded
  product of the lexicon with a suffix family (digits, a year, a symbol, a
  second word);
* enumeration proceeds rule by rule, and within a rule word-major.

A target's rank is the first position at which that enumeration emits it. The
enumeration is never run. Every rule is a product with a known factorisation,
so the rank is recovered by *inverting* the rule -- strip a suffix, look the
stem up, multiply out the indices -- in time linear in the password's length.
The universe is counted, not built. **No cracking wordlist exists at any point
in this pipeline**, which is the same property the PCFG sampler was built to
have, for the same reason.

Independence from the estimators
--------------------------------
This module imports **nothing but the standard library** -- not the meter, the
scoring model, the matcher, the baseline or the PCFG, and not even the
dictionary: :func:`dictionary_lexicon_entries` takes an ``IndicDict`` and reads
two attributes off its entries, so the type is a duck rather than a dependency.
Nothing here reads a guess number. ``tests/`` enforces this three times: by
asserting the import set is stdlib-only, by failing on any estimator module
appearing in it, and by ranking a corpus with all three estimators replaced by
objects that raise on contact.

That is independence in the mechanical sense. There is a second sense in which
it is only partial, and it is stated here rather than in a footnote:

    **The frequency-ordered lexicon shares its evidence with two of the three
    estimators being scored.** IndicPass prices a word at its rank in a
    frequency-ordered wordlist; the PCFG's word distribution is built from the
    same wordfreq table. An attack that orders its lexicon by that table is
    therefore close to the closed form of the Milestone 2 estimator, and
    finding that Milestone 2 predicts it well is close to a tautology.

Which is why :data:`LEXICON_ORDERS` has three entries and the report runs all
of them. ``shuffled`` and ``length`` order the same spellings by criteria no
estimator has access to. A conclusion that holds only under ``frequency`` is a
statement about shared evidence; one that holds across all three is a statement
about the estimators. The report is required to show both.

What this attack does not represent
-----------------------------------
It is one attacker, not the space of them. It has no leaked-password list, no
Markov or PCFG guess generator, no leet substitution, no keyboard walks, no
targeted personal data, and no English wordlist beyond whatever English
spellings IndicDict happens to contain. A password it cannot reach is recorded
as **uncovered** and given no rank -- never a fabricated one -- so coverage is
reported as a number rather than hidden inside an average.
"""

from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from itertools import product
from typing import Any

__all__ = [
    "ATTACK_SYMBOLS",
    "ATTACK_VERSION",
    "LEXICON_ORDERS",
    "RULE_ORDERS",
    "UNCOVERED",
    "AttackRank",
    "AttackSettings",
    "Lexicon",
    "ReferenceAttack",
    "Rule",
    "RuleBlock",
    "Suffix",
    "build_rules",
    "build_suffixes",
    "coverage",
    "dictionary_lexicon_entries",
]

#: Bump when the rule programme, the ordering policy or the rank arithmetic
#: changes. Every report carries it, so a rank can never be silently compared
#: against one produced by a different attack.
ATTACK_VERSION = "1.0"

#: Symbols the attacker appends. The shift-number row plus the four separators
#: that dominate published password-composition studies.
#:
#: This is a strict SUPERSET of the ten symbols the benchmark generator uses.
#: That is deliberate and it is the safe direction: a superset can only push a
#: target further down the enumeration, never closer. Had it been a subset,
#: some targets would have been uncovered because the attacker's symbol list
#: was mismatched rather than because the attack is weak, and coverage would
#: have measured an artefact.
ATTACK_SYMBOLS = "!@#$%^&*()-_.+"

#: How the attacker orders their wordlist. See the module docstring: only the
#: first shares evidence with the estimators, and that is why the other two
#: exist.
LEXICON_ORDERS: tuple[str, ...] = ("frequency", "shuffled", "length")

#: How the rule programme is ordered. ``size`` is the default and is argued
#: for in :func:`build_rules`; ``family`` is the sensitivity arm.
RULE_ORDERS: tuple[str, ...] = ("size", "family")

_CASES: tuple[str, ...] = ("lower", "capitalized", "upper")

#: Suffix families, in the order :data:`RULE_ORDERS` ``"family"`` uses. This
#: ordering is a HEURISTIC reading of how people actually decorate a word --
#: a digit or two, then a year, then a symbol -- and its only job is to be a
#: defensible alternative to ordering by size, so that the report can show
#: whether the conclusion depends on which was chosen.
_SUFFIX_PRECEDENCE: tuple[str, ...] = (
    "",
    "digits1",
    "digits2",
    "year",
    "digits3",
    "symbol",
    "symbol+digits1",
    "symbol+digits2",
    "digits4",
    "symbol+digits3",
    "digits5",
)


# -- the lexicon ------------------------------------------------------------


def dictionary_lexicon_entries(dictionary: Any) -> list[tuple[str, int | None]]:
    """``(spelling, rank)`` pairs from an :class:`IndicDict`, ranks kept as-is.

    Separated from :meth:`Lexicon.build` so that the attack itself depends on
    nothing but the standard library: everything below this line operates on
    plain tuples. ``rank`` is ``None`` for a spelling with no observed corpus
    frequency, and that ``None`` is carried rather than filled in -- the
    orderings below decide what to do with it, explicitly.
    """
    return [
        (entry.romanized_form, entry.rank)
        for entry in dictionary.entries.values()
        if entry.romanized_form == entry.romanized_form.lower()
    ]


@dataclass(frozen=True)
class Lexicon:
    """The attacker's wordlist, in the order they work through it.

    ``words`` is the order; ``index`` is its inverse. Both are needed: the
    attack is defined by the order, and the rank arithmetic needs the inverse
    in constant time.
    """

    order: str
    seed: int
    words: tuple[str, ...]
    index: Mapping[str, int]
    #: How many leading entries were placed by an observed frequency. Zero for
    #: the orderings that use none, which is the number that says so.
    frequency_ordered: int
    #: Where the spellings came from, for the report header.
    source: str

    def __len__(self) -> int:
        return len(self.words)

    def position(self, word: str) -> int | None:
        """0-based position of *word*, or ``None`` if the attacker lacks it."""
        return self.index.get(word)

    @classmethod
    def build(
        cls,
        entries: Iterable[tuple[str, int | None]],
        *,
        order: str = "frequency",
        seed: int = 42,
        size: int | None = None,
        source: str = "IndicDict",
    ) -> Lexicon:
        """Order *entries* by *order*, deterministically.

        ``frequency``
            Entries with an observed corpus rank first, in that rank's order;
            then everything else in seeded-shuffle order. This is what a real
            attacker with a frequency table does -- and it is the arm that
            shares evidence with IndicPass and the PCFG.

        ``shuffled``
            Every spelling in seeded-shuffle order, frequency ignored entirely.
            The attacker holds the wordlist but nothing that orders it. This is
            the arm no estimator has an informational advantage in.

        ``length``
            Shortest first, then alphabetical. A frequency-free heuristic a
            real attacker does use, and unlike ``shuffled`` it is not random --
            so the two together separate "no frequency information" from
            "no information at all".

        The shuffle is seeded from a string rather than an integer so that
        adding an ordering leaves the others' streams untouched.
        """
        if order not in LEXICON_ORDERS:
            raise ValueError(f"Unknown lexicon order {order!r}. Known: {list(LEXICON_ORDERS)}.")

        # Sorted first, so the input's iteration order can never reach the
        # result. A dictionary loaded from a differently-ordered file must
        # produce the same lexicon or the whole experiment is unreproducible.
        pairs = sorted(set(entries))

        if order == "length":
            ordered = [word for word, _ in sorted(pairs, key=lambda p: (len(p[0]), p[0]))]
            frequency_ordered = 0
        elif order == "shuffled":
            ordered = [word for word, _ in pairs]
            random.Random(f"lexicon:{seed}:shuffled").shuffle(ordered)
            frequency_ordered = 0
        else:
            ranked = sorted(
                ((rank, word) for word, rank in pairs if rank is not None),
            )
            rest = [word for word, rank in pairs if rank is None]
            random.Random(f"lexicon:{seed}:frequency").shuffle(rest)
            ordered = [word for _, word in ranked] + rest
            frequency_ordered = len(ranked)

        if size is not None:
            ordered = ordered[:size]
            frequency_ordered = min(frequency_ordered, len(ordered))

        return cls(
            order=order,
            seed=seed,
            words=tuple(ordered),
            index={word: position for position, word in enumerate(ordered)},
            frequency_ordered=frequency_ordered,
            source=source,
        )

    def fingerprint(self) -> str:
        """SHA-256 over the ordered spellings.

        The order *is* the attack, so this is what two runs must agree on for
        their ranks to be comparable. Hashed incrementally: the digest is over
        300k spellings and there is no reason to build that string.
        """
        digest = hashlib.sha256()
        digest.update(f"{ATTACK_VERSION}\n{self.order}\n{self.seed}\n".encode())
        for word in self.words:
            digest.update(word.encode("utf-8"))
            digest.update(b"\n")
        return f"sha256:{digest.hexdigest()}"

    def describe(self) -> dict[str, Any]:
        """Publishable provenance. Holds no spelling."""
        return {
            "order": self.order,
            "seed": self.seed,
            "size": len(self.words),
            "frequency_ordered_entries": self.frequency_ordered,
            "frequency_ordered_share": (
                round(self.frequency_ordered / len(self.words), 6) if self.words else 0.0
            ),
            "source": self.source,
            "fingerprint": self.fingerprint(),
            "shares_evidence_with_estimators": self.order == "frequency",
        }


# -- suffix families --------------------------------------------------------


@dataclass(frozen=True)
class Suffix:
    """What a rule appends to a stem, as a bounded, indexable set.

    A suffix family is a *set of strings with a fixed enumeration order*. That
    is all a rule needs: its size gives the block's width, and the index of a
    concrete string gives the offset. :meth:`split` runs the inverse -- given a
    target, which stems could this family have been appended to.
    """

    name: str
    #: ``none`` | ``digits`` | ``year`` | ``symbol`` | ``symbol_digits``
    kind: str
    digits: int = 0
    year_range: tuple[int, int] = (0, 0)
    symbols: str = ""

    @property
    def size(self) -> int:
        if self.kind == "none":
            return 1
        if self.kind == "digits":
            return 10**self.digits
        if self.kind == "year":
            return self.year_range[1] - self.year_range[0] + 1
        if self.kind == "symbol":
            return len(self.symbols)
        if self.kind == "symbol_digits":
            return len(self.symbols) * 10**self.digits
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    @property
    def width(self) -> int:
        """Characters this suffix occupies, so a stem can be cut off exactly."""
        if self.kind == "none":
            return 0
        if self.kind == "digits":
            return self.digits
        if self.kind == "year":
            return 4
        if self.kind == "symbol":
            return 1
        if self.kind == "symbol_digits":
            return 1 + self.digits
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    def split(self, target: str) -> tuple[str, int] | None:
        """``(stem, suffix index)`` if *target* ends with a member, else ``None``.

        Every family here has a fixed width, so at most one split is possible
        and the inverse is a single test rather than a search. ``digits`` keeps
        leading zeros -- ``007`` is the 7th member of the three-digit family,
        not the 7th of the one-digit family -- because an attacker enumerating
        ``000..999`` really does emit it there.
        """
        width = self.width
        if width == 0:
            return (target, 0)
        if len(target) <= width:
            return None
        stem, tail = target[:-width], target[-width:]

        if self.kind == "digits":
            return (stem, int(tail)) if tail.isdigit() and tail.isascii() else None
        if self.kind == "year":
            if not (tail.isdigit() and tail.isascii()):
                return None
            value = int(tail)
            low, high = self.year_range
            return (stem, value - low) if low <= value <= high else None
        if self.kind == "symbol":
            position = self.symbols.find(tail)
            return (stem, position) if position >= 0 else None
        if self.kind == "symbol_digits":
            symbol, rest = tail[0], tail[1:]
            position = self.symbols.find(symbol)
            if position < 0 or not (rest.isdigit() and rest.isascii()):
                return None
            return (stem, position * 10**self.digits + int(rest))
        raise ValueError(f"Unknown suffix kind {self.kind!r}.")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name or "(none)", "kind": self.kind, "size": self.size}


def build_suffixes(settings: AttackSettings) -> list[Suffix]:
    """Every suffix family the attacker has a rule for."""
    families = [Suffix("", "none")]
    families += [
        Suffix(f"digits{n}", "digits", digits=n) for n in range(1, settings.max_digits + 1)
    ]
    families.append(Suffix("year", "year", year_range=settings.year_range))
    families.append(Suffix("symbol", "symbol", symbols=settings.symbols))
    families += [
        Suffix(f"symbol+digits{n}", "symbol_digits", digits=n, symbols=settings.symbols)
        for n in range(1, settings.max_symbol_digits + 1)
    ]
    return families


# -- rules ------------------------------------------------------------------


def _stem_word(surface: str, case: str) -> str | None:
    """The lexicon entry a cased *surface* came from, or ``None``.

    The ``surface != lowered`` guard on the two cased forms keeps the blocks
    disjoint: a stem with no cased letters is emitted by the ``lower`` rule and
    by no other, so it cannot be reached twice. The block *sizes* still count
    it three times, which over-counts the universe slightly and can only push
    later blocks further out -- the conservative direction.
    """
    lowered = surface.lower()
    if case == "lower":
        return surface if surface == lowered else None
    if case == "capitalized":
        return lowered if surface == lowered.capitalize() and surface != lowered else None
    if case == "upper":
        return lowered if surface == lowered.upper() and surface != lowered else None
    raise ValueError(f"Unknown case {case!r}. Known: {list(_CASES)}.")


@dataclass(frozen=True)
class Rule:
    """One transformation family: a stem shape, a case, and a suffix.

    ``base`` is ``word`` (one lexicon entry) or ``word2`` (two concatenated --
    the combinator attack). ``case`` applies to the FIRST word only, which is
    what people actually do and what the benchmark generator happens to
    produce; a second word capitalised mid-password is not modelled and any
    password shaped that way is reported uncovered rather than approximated.
    """

    base: str
    case: str
    suffix: Suffix

    @property
    def name(self) -> str:
        """Shape only -- safe to publish, and what a report's rows are keyed on."""
        stem = "word+word" if self.base == "word2" else "word"
        tail = f"+{self.suffix.name}" if self.suffix.name else ""
        return f"{stem}{tail}/{self.case}"

    def base_size(self, lexicon_size: int) -> int:
        return lexicon_size**2 if self.base == "word2" else lexicon_size

    def size(self, lexicon_size: int) -> int:
        return self.base_size(lexicon_size) * self.suffix.size

    def offsets(self, stem: str, lexicon: Lexicon) -> Iterator[int]:
        """Positions within this rule's base that emit *stem*.

        ``word`` yields at most one. ``word2`` yields one per split point that
        lands on two entries the attacker holds, and the caller takes the
        minimum -- an ambiguous concatenation is reached at the first of its
        readings, not at all of them.
        """
        if self.base == "word":
            word = _stem_word(stem, self.case)
            if word is None:
                return
            position = lexicon.position(word)
            if position is not None:
                yield position
            return

        size = len(lexicon)
        for cut in range(1, len(stem)):
            right = stem[cut:]
            if right != right.lower():
                continue
            second = lexicon.position(right)
            if second is None:
                continue
            word = _stem_word(stem[:cut], self.case)
            if word is None:
                continue
            first = lexicon.position(word)
            if first is not None:
                yield first * size + second

    def to_dict(self, lexicon_size: int) -> dict[str, Any]:
        return {
            "name": self.name,
            "base": self.base,
            "case": self.case,
            "suffix": self.suffix.to_dict(),
            "size": self.size(lexicon_size),
        }


def build_rules(settings: AttackSettings, lexicon_size: int) -> list[Rule]:
    """The rule programme, in the order the attacker runs it.

    Ordering by **ascending block size** is the default, and it is a stated
    assumption rather than a tuned choice. The argument for it: absent any
    information about which rule the target was built with, treating the rules
    as equally likely to contain it makes expected cracks-per-guess inversely
    proportional to block size, so smallest-first maximises yield. It is the
    same maximum-entropy move the PCFG's structure prior makes, for the same
    reason -- there is no password corpus here to learn a better order from.

    ``family`` is the alternative: an explicit, human-written precedence over
    suffix families (:data:`_SUFFIX_PRECEDENCE`), stems and cases. It exists so
    the report can answer "does the conclusion depend on the rule order?" with
    a measurement instead of an opinion.
    """
    if settings.rule_order not in RULE_ORDERS:
        raise ValueError(
            f"Unknown rule order {settings.rule_order!r}. Known: {list(RULE_ORDERS)}."
        )

    bases = ("word", "word2") if settings.combinator else ("word",)
    rules = [
        Rule(base=base, case=case, suffix=suffix)
        for base, case, suffix in product(bases, _CASES, build_suffixes(settings))
    ]

    def family_key(rule: Rule) -> tuple[int, int, int]:
        return (
            bases.index(rule.base),
            _SUFFIX_PRECEDENCE.index(rule.suffix.name),
            _CASES.index(rule.case),
        )

    if settings.rule_order == "size":
        # Ties are broken by the family precedence, NOT alphabetically. Blocks
        # of equal width are common -- the three case rules on any one suffix
        # are all the same size -- and an alphabetical tie-break would run
        # `word/capitalized` before `word/lower`, making a capitalised word
        # cheaper to reach than the plain one. Every published rule set runs
        # the straight wordlist first, and so does this.
        return sorted(rules, key=lambda rule: (rule.size(lexicon_size), family_key(rule)))
    return sorted(rules, key=family_key)


@dataclass(frozen=True)
class RuleBlock:
    """One rule, placed: how many candidates precede it and how many it holds."""

    rule: Rule
    offset: int
    size: int

    @property
    def name(self) -> str:
        return self.rule.name

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.rule.name,
            "base": self.rule.base,
            "case": self.rule.case,
            "suffix": self.rule.suffix.name or "(none)",
            "offset": self.offset,
            "size": self.size,
            "log10_offset": round(math.log10(self.offset), 4) if self.offset else 0.0,
        }


# -- settings ---------------------------------------------------------------


@dataclass(frozen=True)
class AttackSettings:
    """Everything that defines the attack. Serialised into every report.

    ``max_candidates`` is the attacker's **budget**, and it is the reason
    "uncovered" has a meaning beyond "not in the wordlist": rules are added
    cheapest-first until the budget is exhausted, and a password only the
    dropped rules could produce is out of reach. At the default 10^16 that is
    about two hours of a single eight-GPU rig against MD5, and about thirty
    million years against bcrypt at cost 10 -- so the same number is a
    formality for one hash and impossible for another, which is the honest way
    to state an attack budget.

    The default is deliberately large enough that coverage measures the
    *lexicon* rather than the budget. That is a stated design choice, not a
    tuned one, and ``budget`` arms in the report show what a smaller one costs.
    """

    lexicon_order: str = "frequency"
    lexicon_size: int | None = None
    seed: int = 42
    max_candidates: float = 1e16
    year_range: tuple[int, int] = (1940, 2029)
    symbols: str = ATTACK_SYMBOLS
    max_digits: int = 5
    max_symbol_digits: int = 3
    combinator: bool = True
    rule_order: str = "size"

    @classmethod
    def from_config(cls, section: Mapping[str, Any]) -> AttackSettings:
        years = section.get("year_range") or [1940, 2029]
        return cls(
            lexicon_order=str(section.get("lexicon_order", "frequency")),
            lexicon_size=(
                int(section["lexicon_size"]) if section.get("lexicon_size") else None
            ),
            seed=int(section.get("seed", 42)),
            max_candidates=float(section.get("max_candidates", 1e16)),
            year_range=(int(years[0]), int(years[1])),
            symbols=str(section.get("symbols", ATTACK_SYMBOLS)),
            max_digits=int(section.get("max_digits", 5)),
            max_symbol_digits=int(section.get("max_symbol_digits", 3)),
            combinator=bool(section.get("combinator", True)),
            rule_order=str(section.get("rule_order", "size")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "lexicon_order": self.lexicon_order,
            "lexicon_size": self.lexicon_size,
            "seed": self.seed,
            "max_candidates": self.max_candidates,
            "log10_max_candidates": round(math.log10(self.max_candidates), 4),
            "year_range": list(self.year_range),
            "symbols": self.symbols,
            "symbol_count": len(self.symbols),
            "max_digits": self.max_digits,
            "max_symbol_digits": self.max_symbol_digits,
            "combinator": self.combinator,
            "rule_order": self.rule_order,
        }


# -- the attack -------------------------------------------------------------


@dataclass(frozen=True)
class AttackRank:
    """Where the attack reached a password, or that it never did.

    Holds no password and no lexicon entry: ``rule`` is a shape like
    ``word+year/capitalized``, the same class of information as the benchmark's
    ``construction``, and is what makes a coverage table readable.

    ``rank`` is ``None`` when the password is uncovered. It is never a
    substituted value, a censored bound, or the universe size -- an uncovered
    target contributes to the coverage figure and to nothing else.
    """

    covered: bool
    rank: int | None = None
    log10_rank: float | None = None
    rule: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "covered": self.covered,
            "rank": self.rank,
            "log10_rank": round(self.log10_rank, 6) if self.log10_rank is not None else None,
            "rule": self.rule,
        }


#: Returned for every uncovered target, rather than a fresh object each time.
UNCOVERED = AttackRank(covered=False)


@dataclass(frozen=True)
class ReferenceAttack:
    """A fully specified attacker, and the ranks they produce.

    Construct with :meth:`build`, then call :meth:`rank`. The object is
    immutable and holds no state between calls, so ranking a corpus twice in
    one process gives the same answer as ranking it in two.
    """

    settings: AttackSettings
    lexicon: Lexicon
    blocks: tuple[RuleBlock, ...]
    universe_size: int
    #: Rules the budget could not afford, cheapest-first order preserved.
    dropped: tuple[str, ...]

    @classmethod
    def build(cls, lexicon: Lexicon, settings: AttackSettings) -> ReferenceAttack:
        """Place every rule the budget allows, in enumeration order."""
        size = len(lexicon)
        if size == 0:
            raise ValueError("The attacker's lexicon is empty; there is nothing to enumerate.")

        blocks: list[RuleBlock] = []
        dropped: list[str] = []
        offset = 0
        for rule in build_rules(settings, size):
            width = rule.size(size)
            # Cheapest-first ordering means the first unaffordable rule is
            # followed only by rules at least as wide -- but they are checked
            # individually anyway, because the `family` ordering is not sorted
            # by size and a later rule there really can be affordable.
            if offset + width > settings.max_candidates:
                dropped.append(rule.name)
                continue
            blocks.append(RuleBlock(rule=rule, offset=offset, size=width))
            offset += width

        if not blocks:
            raise ValueError(
                f"No rule fits a budget of {settings.max_candidates:.3g} candidates "
                f"against a {size:,}-entry lexicon. Raise max_candidates."
            )

        return cls(
            settings=settings,
            lexicon=lexicon,
            blocks=tuple(blocks),
            universe_size=offset,
            dropped=tuple(dropped),
        )

    def rank(self, password: str) -> AttackRank:
        """The 1-based position at which this attack emits *password*.

        Blocks are in enumeration order, so the first block that can produce
        the password holds its rank: every position in a later block is beyond
        every position in an earlier one. Within the block the minimum offset
        wins, which matters for ``word+word`` -- a concatenation readable two
        ways is reached at the earlier reading.
        """
        if not password:
            return UNCOVERED

        for block in self.blocks:
            split = block.rule.suffix.split(password)
            if split is None:
                continue
            stem, suffix_index = split
            if not stem:
                continue
            offsets = list(block.rule.offsets(stem, self.lexicon))
            if not offsets:
                continue
            within = min(offsets) * block.rule.suffix.size + suffix_index
            rank = block.offset + within + 1
            return AttackRank(
                covered=True,
                rank=rank,
                log10_rank=math.log10(rank),
                rule=block.name,
            )
        return UNCOVERED

    def rank_all(self, passwords: Sequence[str]) -> list[AttackRank]:
        return [self.rank(password) for password in passwords]

    def stem_in_lexicon(self, password: str) -> bool:
        """Can the attacker's wordlist produce this password's leading word run?

        The "unseen spelling" family is not a benchmark category -- it is a
        property of the attacker's lexicon, so it has to be *measured* against
        the lexicon rather than generated. This is that measurement: take the
        leading run of letters and ask whether the stem model can emit it, by
        exactly the machinery :meth:`rank` uses.

        Answering with the same code is the point. A separate membership test
        would drift from the rule programme -- it would miss, for instance,
        that ``Mera`` is producible although the dictionary key is ``mera`` --
        and the stratum would then describe something other than the attack.
        """
        head = ""
        for character in password:
            if not character.isalpha():
                break
            head += character
        if not head:
            return False

        bases = ("word", "word2") if self.settings.combinator else ("word",)
        none_suffix = Suffix("", "none")
        for base, case in product(bases, _CASES):
            rule = Rule(base=base, case=case, suffix=none_suffix)
            if next(rule.offsets(head, self.lexicon), None) is not None:
                return True
        return False

    def fingerprint(self) -> str:
        """SHA-256 over the lexicon order and the placed rule programme.

        Two runs agreeing on this agree on every rank they can produce, which
        is the reproducibility claim the report is allowed to make.
        """
        digest = hashlib.sha256()
        digest.update(f"{ATTACK_VERSION}\n{self.lexicon.fingerprint()}\n".encode())
        for block in self.blocks:
            digest.update(f"{block.name}\t{block.offset}\t{block.size}\n".encode())
        return f"sha256:{digest.hexdigest()}"

    def describe(self) -> dict[str, Any]:
        """Everything a reader needs to reproduce or dispute the attack."""
        return {
            "attack_version": ATTACK_VERSION,
            "settings": self.settings.to_dict(),
            "lexicon": self.lexicon.describe(),
            "universe_size": self.universe_size,
            "log10_universe_size": round(math.log10(self.universe_size), 4),
            "rules_placed": len(self.blocks),
            "rules_dropped": list(self.dropped),
            "blocks": [block.to_dict() for block in self.blocks],
            "fingerprint": self.fingerprint(),
            "independence_note": (
                "Candidate generation and ordering use the dictionary's spellings and "
                "(under lexicon_order=frequency) its observed corpus ranks. They use no "
                "IndicPass, PCFG or zxcvbn output of any kind. The frequency ordering "
                "nevertheless SHARES EVIDENCE with IndicPass and the PCFG, both of which "
                "are built on the same wordfreq table; the shuffled and length orderings "
                "share none, and a conclusion is only safe where the arms agree."
            ),
            "coverage_note": (
                "An uncovered password is given no rank. It is never assigned the "
                "universe size, a censored bound, or any substituted value."
            ),
        }


def coverage(ranks: Sequence[AttackRank]) -> dict[str, Any]:
    """Covered share of *ranks*, and the rules that did the covering."""
    if not ranks:
        return {"targets": 0, "covered": 0, "coverage": 0.0, "rules": {}}
    used: dict[str, int] = {}
    for entry in ranks:
        if entry.rule:
            used[entry.rule] = used.get(entry.rule, 0) + 1
    covered = sum(1 for entry in ranks if entry.covered)
    return {
        "targets": len(ranks),
        "covered": covered,
        "coverage": round(covered / len(ranks), 4),
        "rules": dict(sorted(used.items(), key=lambda item: (-item[1], item[0]))),
    }
